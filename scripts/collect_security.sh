#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 && -d /run/systemd/system ]] || { echo 'Run as root inside the VM.' >&2; exit 1; }
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
output="${project_root}/evidence/vm/system"
install -d -o root -g root -m 0755 "${output}"
date --iso-8601=seconds > "${output}/collected-at.txt"
{
    cat /etc/os-release
    python3 --version
    python3 -m pip --version
    git --version
    docker --version
    docker compose version
    docker version
} > "${output}/versions.txt" 2>&1
ufw status verbose > "${output}/ufw-status.txt"
ufw status numbered > "${output}/ufw-numbered.txt"
ss -tulpn > "${output}/listening-ports.txt"
/usr/sbin/sshd -t > "${output}/sshd-syntax.txt" 2>&1
printf 'sshd -t exit code: 0\n' >> "${output}/sshd-syntax.txt"
/usr/sbin/sshd -T -C user=root,host=localhost,addr=127.0.0.1 > "${output}/sshd-effective-root.txt"
/usr/sbin/sshd -T -C user=mluser,host=localhost,addr=127.0.0.1 > "${output}/sshd-effective-mluser.txt"
{
    id mluser
    getent group sudo
    getent group docker
    stat -c '%U %G %a %n' /home/mluser/.ssh /home/mluser/.ssh/authorized_keys
} > "${output}/user-and-key-permissions.txt"
{
    cd "${project_root}"
    sha256sum data/raw/SMSSpamCollection data/raw/sms_spam_collection.zip
    sha256sum --check /var/lib/ml-lab/integrity/SHA256SUMS
    stat -c '%U %G %a %n' /var/lib/ml-lab/integrity /var/lib/ml-lab/integrity/*
} > "${output}/sha256.txt"
docker ps --format '{{.Names}}\t{{.Ports}}' > "${output}/docker-ports.txt"
systemctl --no-pager --type=service --state=running > "${output}/running-services.txt"
apt list --upgradable > "${output}/apt-upgradable-final.txt" 2>&1
cp -a /var/log/ml-lab/. "${output}/"
cp -a /var/log/apt/history.log "${output}/apt-history.log"
if [[ -f /var/run/reboot-required ]]; then
    cp /var/run/reboot-required "${output}/REBOOT_REQUIRED.txt"
fi
chmod -R a+rX "${output}"
echo "Evidence collected in ${output}. No private key or Jupyter token was collected."

