#!/usr/bin/env bash
# Выполнять только в отдельной учебной Ubuntu 24.04 VM от администратора.
set -Eeuo pipefail
umask 022
[[ ${EUID} -eq 0 ]] || { echo 'Run through sudo on the lab VM.' >&2; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'A systemd VM is required; containers are not supported.' >&2; exit 1; }
source /etc/os-release
[[ ${ID} == ubuntu && ${VERSION_ID} == 24.04 ]] || { echo 'This script targets Ubuntu 24.04.' >&2; exit 1; }
install -d -o root -g root -m 0755 /var/log/ml-lab
exec > >(tee /var/log/ml-lab/system-install.log) 2>&1
date --iso-8601=seconds
id
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
apt-get -o DPkg::Lock::Timeout=600 update
apt list --upgradable 2>&1 | tee /var/log/ml-lab/apt-upgradable-before.txt
apt-get -o DPkg::Lock::Timeout=600 upgrade --with-new-pkgs -y
apt-get -o DPkg::Lock::Timeout=600 install -y \
    git python3 python3-pip python3-venv openssh-server ufw iproute2 \
    ca-certificates curl unzip jq docker.io docker-compose-v2
systemctl enable --now ssh
systemctl enable --now docker
apt list --upgradable 2>&1 | tee /var/log/ml-lab/apt-upgradable-after.txt
dpkg-query -W -f='${binary:Package}\t${Version}\n' > /var/log/ml-lab/apt-installed.txt
ss -tulpn > /var/log/ml-lab/ports-before-hardening.txt
python3 --version
python3 -m pip --version
git --version
docker --version
docker compose version
if [[ -f /var/run/reboot-required ]]; then
    echo 'REBOOT_REQUIRED: reboot the VM before the final evidence collection.'
fi
echo 'System packages installed. The development user was not added to sudo or docker.'

