#!/usr/bin/env bash
# После успешного входа mluser по ключу. Активную сессию не закрывать.
set -Eeuo pipefail
umask 022
[[ ${EUID} -eq 0 && -d /run/systemd/system ]] || { echo 'Run as root inside the lab VM.' >&2; exit 1; }
[[ ${1:-} == --key-login-verified ]] || { echo 'Verify a NEW mluser SSH key session before this step.' >&2; exit 1; }
[[ -s /home/mluser/.ssh/authorized_keys ]] || { echo 'No mluser public key found.' >&2; exit 1; }
[[ -f /home/mluser/.lab1-key-verified ]] || { echo 'Missing marker from the successful SSH key session.' >&2; exit 1; }
install -d -o root -g root -m 0755 /var/log/ml-lab /var/lib/ml-lab
exec > >(tee /var/log/ml-lab/hardening.log) 2>&1
mapfile -t ports < <(/usr/sbin/sshd -T | awk '$1 == "port" {print $2}')
[[ ${#ports[@]} -eq 1 && ${ports[0]} =~ ^[0-9]+$ ]] || { echo 'Review multiple SSH ports manually.' >&2; exit 1; }
ssh_port=${ports[0]}
echo "Actual SSH port: ${ssh_port}"
dropin=/etc/ssh/sshd_config.d/00-ml-lab.conf
backup=/var/lib/ml-lab/ssh-dropin-before.conf
if [[ -e /var/lib/ml-lab/hardening-pending ]]; then
    echo 'Recovering an unfinished hardening run before retrying.'
    previous_unit=$(cat /var/lib/ml-lab/rollback-unit)
    [[ ${previous_unit} =~ ^ml-lab-rollback-[0-9]+-[0-9]+$ ]] || { echo 'Invalid rollback unit; manual review required.' >&2; exit 1; }
    systemctl stop "${previous_unit}.timer" "${previous_unit}.service" || true
    /var/lib/ml-lab/rollback.sh
    [[ ! -e /var/lib/ml-lab/hardening-pending ]] || { echo 'Previous rollback did not finish.' >&2; exit 1; }
fi
if [[ -e ${dropin} ]]; then cp -a "${dropin}" "${backup}"; else rm -f "${backup}"; fi
cp -a /etc/ssh/sshd_config /var/lib/ml-lab/sshd_config-before
cat > /var/lib/ml-lab/rollback.sh <<'ROLLBACK'
#!/usr/bin/env bash
set -u
if [[ ! -f /var/lib/ml-lab/hardening-pending ]]; then exit 0; fi
if [[ -f /var/lib/ml-lab/ssh-dropin-before.conf ]]; then
    cp /var/lib/ml-lab/ssh-dropin-before.conf /etc/ssh/sshd_config.d/00-ml-lab.conf
else
    rm -f /etc/ssh/sshd_config.d/00-ml-lab.conf
fi
/usr/sbin/sshd -t && systemctl reload ssh
ufw --force disable
rm -f /var/lib/ml-lab/hardening-pending
date --iso-8601=seconds > /var/log/ml-lab/ROLLBACK_OCCURRED.txt
ROLLBACK
chmod 0700 /var/lib/ml-lab/rollback.sh
touch /var/lib/ml-lab/hardening-pending
rollback_unit="ml-lab-rollback-$(date +%s)-${RANDOM}"
printf '%s\n' "${rollback_unit}" > /var/lib/ml-lab/rollback-unit
rollback_on_error() {
    local lab_rc=$?
    trap - ERR
    echo "Hardening failed (exit ${lab_rc}); restoring the previous SSH settings and disabling guest UFW."
    systemctl stop "${rollback_unit}.timer" || true
    /var/lib/ml-lab/rollback.sh || true
    exit "${lab_rc}"
}
trap rollback_on_error ERR
systemd-run --unit="${rollback_unit}" --on-active=180s /var/lib/ml-lab/rollback.sh
cat > "${dropin}" <<'SSHCONFIG'
PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
X11Forwarding no
AllowTcpForwarding local
GatewayPorts no
SSHCONFIG
chmod 0644 "${dropin}"
if ! /usr/sbin/sshd -t; then
    /var/lib/ml-lab/rollback.sh
    exit 1
fi
/usr/sbin/sshd -T -C user=mluser,host=localhost,addr=127.0.0.1 > /var/log/ml-lab/sshd-effective-mluser.txt
/usr/sbin/sshd -T -C user=root,host=localhost,addr=127.0.0.1 > /var/log/ml-lab/sshd-effective-root.txt
for context in mluser root; do
    grep -qx 'permitrootlogin no' "/var/log/ml-lab/sshd-effective-${context}.txt"
    grep -qx 'passwordauthentication no' "/var/log/ml-lab/sshd-effective-${context}.txt"
    grep -qx 'kbdinteractiveauthentication no' "/var/log/ml-lab/sshd-effective-${context}.txt"
done
systemctl reload ssh
# prepend также работает с пустым списком; insert 1 в этом случае отклоняется.
ufw prepend limit "${ssh_port}/tcp"
# На новой VM этих правил нет. Если они появились, удаляем безусловные разрешения.
ufw --force delete allow "${ssh_port}/tcp" || true
ufw --force delete allow OpenSSH || true
ufw logging on
ufw logging high
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
ufw status verbose
ufw status numbered
ss -tulpn
echo 'Rollback timer active for 180 seconds. Verify NEW key login and root denial now.'
echo 'Then run: sudo bash scripts/confirm_hardening.sh'

