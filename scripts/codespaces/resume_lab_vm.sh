#!/usr/bin/env bash
# Возобновляет существующий диск ЛР1; не меняет SSH, UFW или cloud-init seed.
set -Eeuo pipefail
state=${1:?Private .labvm directory is required}
[[ ${CODESPACES:-} == true && ${EUID} -ne 0 ]] || { echo 'Run as the Codespace development user.' >&2; exit 1; }
for name in disk.qcow2 seed.iso client_key ssh_config; do
    [[ -f ${state}/${name} ]] || { echo "Missing saved VM file: ${name}. Restore the lab1 Codespace." >&2; exit 1; }
done
sudo -n true
if ! command -v qemu-system-x86_64 >/dev/null; then
    sudo -n apt-get -o DPkg::Lock::Timeout=600 update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y --no-install-recommends qemu-system-x86 qemu-utils
fi
sudo -n python3 -c 'import os,fcntl; k=os.open("/dev/kvm",os.O_RDWR); v=fcntl.ioctl(k,0xAE01,0); os.close(v); os.close(k); print("KVM_OK")'
control_id=$(printf '%s' "${state}" | sha256sum | cut -c1-12)
control_dir="/tmp/ml-lab-ssh-$(id -u)-${control_id}"
mkdir -p "${control_dir}"
chmod 0700 "${control_dir}"
running=false
if [[ -f ${state}/qemu.pid ]]; then
    vm_pid=$(sudo -n cat -- "${state}/qemu.pid")
    if [[ ${vm_pid} =~ ^[0-9]+$ ]] && sudo -n test -r "/proc/${vm_pid}/cmdline"; then
        if sudo -n python3 - "${vm_pid}" "${state}/disk.qcow2" <<'PY'
from pathlib import Path
import sys
args=Path('/proc/'+sys.argv[1]+'/cmdline').read_bytes().split(b'\0')
raise SystemExit(0 if any(sys.argv[2].encode() in arg for arg in args) else 1)
PY
        then running=true; fi
    fi
fi
if [[ ${running} == false ]]; then
    if [[ -S ${state}/console.sock ]]; then sudo -n rm -- "${state}/console.sock"; fi
    sudo -n qemu-system-x86_64 \
        -name ml-lab -machine pc,accel=kvm -cpu host -smp 2 -m 4096 \
        -drive "file=${state}/disk.qcow2,if=virtio,format=qcow2" \
        -drive "file=${state}/seed.iso,format=raw,media=cdrom,readonly=on" \
        -netdev user,id=net0,hostfwd=tcp:127.0.0.1:22222-:22 \
        -device virtio-net-pci,netdev=net0 -display none -monitor none \
        -chardev "socket,id=console,path=${state}/console.sock,server=on,wait=off,logfile=${state}/serial.log" \
        -serial chardev:console -rtc base=utc -daemonize -pidfile "${state}/qemu.pid"
fi
deadline=$((SECONDS+360))
while ((SECONDS<deadline)); do
    if ssh -F "${state}/ssh_config" ml-lab-admin 'sudo test -f /var/lib/ml-lab/managed-by-lab1' 2> "${state}/lab2-ssh-wait.log"; then
        echo 'Saved Ubuntu VM is available.'
        exit 0
    fi
    echo 'Waiting for the saved Ubuntu SSH service...'
    sleep 15
done
cat "${state}/lab2-ssh-wait.log" >&2
echo 'SSH did not become available. The serial console and VM disk are preserved.' >&2
exit 1
