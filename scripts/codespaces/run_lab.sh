#!/usr/bin/env bash
# Запускать обычным пользователем только внутри собственного GitHub Codespace.
set -Eeuo pipefail
umask 077
project_root=$(pwd -P)
vm_state=${1:?Private VM state directory is required}
[[ ${CODESPACES:-} == true ]] || { echo 'This launcher is intended for GitHub Codespaces.' >&2; exit 1; }
[[ ${EUID} -ne 0 ]] || { echo 'Run bash lab1-codespaces.sh without sudo.' >&2; exit 1; }
mkdir -p "${vm_state}" evidence/client
chmod 0700 "${vm_state}"
exec > >(tee -a "${vm_state}/launcher.log") 2>&1
lab_stage='preflight'
on_error() {
    local lab_rc=$?
    printf '\nLAB_STOPPED: stage=%s, exit=%s\n' "${lab_stage}" "${lab_rc}"
    echo 'VM and its disk are preserved. Log: .labvm/launcher.log'
    echo 'Send the last lines of this log if assistance is needed.'
    exit "${lab_rc}"
}
trap on_error ERR
step() { lab_stage=$1; printf '\n===== %s =====\n' "${lab_stage}"; }
sudo -n true
command -v python3 >/dev/null || { echo 'Python 3 is required in the base Codespace.' >&2; exit 1; }
sudo -n python3 -c 'import os,fcntl; k=os.open("/dev/kvm",os.O_RDWR); v=fcntl.ioctl(k,0xAE01,0); os.close(v); os.close(k); print("KVM_OK")'
missing_prerequisite=false
for program in qemu-system-x86_64 qemu-img cloud-localds git ssh ssh-keygen scp curl; do
    if ! command -v "${program}" >/dev/null; then missing_prerequisite=true; fi
done
if [[ ${missing_prerequisite} == true ]]; then
    echo 'Installing QEMU and launcher prerequisites in this Codespace...'
    sudo -n apt-get -o DPkg::Lock::Timeout=600 update
    sudo -n env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a \
        apt-get -o DPkg::Lock::Timeout=600 install -y --no-install-recommends \
        qemu-system-x86 qemu-utils cloud-image-utils git openssh-client curl ca-certificates
fi
for program in qemu-system-x86_64 qemu-img cloud-localds python3 ssh ssh-keygen scp curl; do
    command -v "${program}" >/dev/null || { echo "Missing prerequisite: ${program}" >&2; exit 1; }
done
{
    date --iso-8601=seconds
    id
    qemu-system-x86_64 --version
    git --version
} > evidence/client/codespaces-host.txt
if command -v code >/dev/null && code --version > evidence/client/vscode-version.txt 2>/dev/null; then
    :
elif [[ ${TERM_PROGRAM:-} == vscode && -n ${TERM_PROGRAM_VERSION:-} ]]; then
    printf 'VS Code Web terminal version: %s\n' "${TERM_PROGRAM_VERSION}" > evidence/client/vscode-version.txt
else
    rm -f evidence/client/vscode-version.txt
fi

step '1/9: downloading and checking the official Ubuntu 24.04 cloud image'
python3 - "${vm_state}" "${project_root}/evidence/client" <<'PY'
from pathlib import Path
import hashlib, json, re, sys, urllib.request, datetime
state, evidence = map(Path, sys.argv[1:])
base = state / 'ubuntu-base.img'
record_path = state / 'image-source.json'
name = 'noble-server-cloudimg-amd64.img'
source = 'https://cloud-images.ubuntu.com/noble/current/'
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return h.hexdigest()
if base.exists() and record_path.exists():
    record = json.loads(record_path.read_text())
    if digest(base) != record['sha256']:
        raise SystemExit('Cached Ubuntu image changed; refusing to use it.')
    print('Cached Ubuntu image SHA256: OK', flush=True)
else:
    if base.exists():
        raise SystemExit('An image without its reference record already exists; inspect .labvm/.')
    with urllib.request.urlopen(source+'SHA256SUMS',timeout=60) as response:
        sums=response.read().decode()
    expected=None
    for line in sums.splitlines():
        parts=line.split(maxsplit=1)
        if len(parts)==2 and parts[1].lstrip('*').strip()==name:
            expected=parts[0].lower()
    if not expected or not re.fullmatch('[0-9a-f]{64}',expected):
        raise SystemExit('The Ubuntu checksum file did not contain the expected image.')
    temporary=state/'ubuntu-base.img.part'
    request=urllib.request.Request(source+name,headers={'User-Agent':'ml-lab1-codespaces/1.0'})
    print('Downloading Ubuntu image; this can take several minutes...',flush=True)
    with urllib.request.urlopen(request,timeout=90) as response, temporary.open('wb') as stream:
        downloaded=0
        while True:
            block=response.read(1024*1024)
            if not block: break
            stream.write(block)
            downloaded+=len(block)
            if downloaded%(128*1024*1024)==0: print(f'Downloaded {downloaded//(1024*1024)} MiB',flush=True)
            if downloaded>4*1024**3: raise SystemExit('Unexpectedly large Ubuntu image')
    if digest(temporary)!=expected:
        raise SystemExit('Ubuntu SHA256 mismatch. No VM was booted.')
    temporary.replace(base)
    base.chmod(0o444)
    record={'url':source+name,'checksum_url':source+'SHA256SUMS','sha256':expected,
            'bytes':base.stat().st_size,'retrieved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'trust':'HTTPS source and published checksum; independent GPG signature verification was not performed.'}
    record_path.write_text(json.dumps(record,indent=2)+'\n')
evidence.mkdir(exist_ok=True,parents=True)
(evidence/'ubuntu-image-source.json').write_text(json.dumps(record,indent=2)+'\n')
print('Ubuntu image SHA256:',record['sha256'],flush=True)
PY

step '2/9: preparing private keys, NoCloud seed and the VM'
for name in client_key host_key; do
    if [[ ! -f ${vm_state}/${name} ]]; then
        ssh-keygen -q -t ed25519 -a 64 -N '' -f "${vm_state}/${name}" -C "ml-lab-${name}"
    fi
    chmod 0600 "${vm_state}/${name}"
done
python3 scripts/codespaces/make_seed.py "${vm_state}"
if [[ ! -f ${vm_state}/disk.qcow2 ]]; then
    qemu-img create -f qcow2 -F qcow2 -b "${vm_state}/ubuntu-base.img" "${vm_state}/disk.qcow2" 30G
fi
if [[ ! -f ${vm_state}/seed.iso ]]; then
    cloud-localds "${vm_state}/seed.iso" "${vm_state}/user-data" "${vm_state}/meta-data"
fi
chmod 0600 "${vm_state}/seed.iso"
control_id=$(printf '%s' "${vm_state}" | sha256sum | cut -c1-12)
control_dir="/tmp/ml-lab-ssh-$(id -u)-${control_id}"
mkdir -p "${control_dir}"
chmod 0700 "${control_dir}"
printf '[127.0.0.1]:22222 %s\n' "$(cat "${vm_state}/host_key.pub")" > "${vm_state}/known_hosts"
cat > "${vm_state}/ssh_config" <<CONF
Host ml-lab ml-lab-admin
    HostName 127.0.0.1
    Port 22222
    IdentityFile "${vm_state}/client_key"
    UserKnownHostsFile "${vm_state}/known_hosts"
    HostKeyAlgorithms ssh-ed25519
    StrictHostKeyChecking yes
    IdentitiesOnly yes
    BatchMode yes
    PreferredAuthentications publickey
    ConnectTimeout 5
    ConnectionAttempts 1
    ServerAliveInterval 15
    ServerAliveCountMax 3
    ControlMaster auto
    ControlPersist 120
    ControlPath ${control_dir}/%C
Host ml-lab
    User mluser
Host ml-lab-admin
    User labadmin
CONF
vm_admin() { ssh -F "${vm_state}/ssh_config" ml-lab-admin "$@"; }
vm_user() { ssh -F "${vm_state}/ssh_config" ml-lab "$@"; }
wait_for_guest() {
    local lab_deadline=$((SECONDS+360))
    local lab_next_message=0
    while (( SECONDS<lab_deadline )); do
        if ssh -F "${vm_state}/ssh_config" -o ControlMaster=no -o ControlPath=none ml-lab-admin true 2> "${vm_state}/ssh-wait.log"; then
            return 0
        fi
        if (( SECONDS>=lab_next_message )); then
            echo 'Waiting for the Ubuntu SSH service...'
            lab_next_message=$((SECONDS+20))
        fi
        sleep 2
    done
    cat "${vm_state}/ssh-wait.log" >&2
    echo 'Guest SSH did not become available; inspect .labvm/serial.log.' >&2
    return 1
}
vm_running=false
if [[ -f ${vm_state}/qemu.pid ]]; then
    # QEMU запущен через sudo и создаёт закрытый PID-файл от root.
    vm_pid=$(sudo -n cat -- "${vm_state}/qemu.pid")
    if [[ ${vm_pid} =~ ^[0-9]+$ ]] && sudo -n test -r "/proc/${vm_pid}/cmdline"; then
        if sudo -n python3 - "${vm_pid}" "${vm_state}/disk.qcow2" <<'PY'
import sys
from pathlib import Path
args=Path('/proc/'+sys.argv[1]+'/cmdline').read_bytes().split(b'\0')
raise SystemExit(0 if any(sys.argv[2].encode() in arg for arg in args) else 1)
PY
        then vm_running=true; fi
    fi
fi
if [[ ${vm_running} == false ]]; then
    if [[ -S ${vm_state}/console.sock ]]; then
        sudo -n rm -- "${vm_state}/console.sock"
    fi
    sudo -n qemu-system-x86_64 \
        -name ml-lab -machine pc,accel=kvm -cpu host -smp 2 -m 4096 \
        -drive "file=${vm_state}/disk.qcow2,if=virtio,format=qcow2" \
        -drive "file=${vm_state}/seed.iso,format=raw,media=cdrom,readonly=on" \
        -netdev user,id=net0,hostfwd=tcp:127.0.0.1:22222-:22 \
        -device virtio-net-pci,netdev=net0 \
        -display none -monitor none \
        -chardev "socket,id=console,path=${vm_state}/console.sock,server=on,wait=off,logfile=${vm_state}/serial.log" \
        -serial chardev:console -rtc base=utc \
        -daemonize -pidfile "${vm_state}/qemu.pid"
fi
wait_for_guest
vm_admin 'sudo cloud-init status --wait'
vm_admin 'sudo test -f /var/lib/ml-lab/managed-by-lab1'

step '3/9: copying the project into the guest VM'
scp -F "${vm_state}/ssh_config" "${vm_state}/project.zip" ml-lab:/home/mluser/ml-lab-source.zip
vm_user 'python3 -' <<'PY'
import hashlib, os, zipfile
from pathlib import Path
base=Path('/home/mluser/ml-project')
base.mkdir(exist_ok=True)
with zipfile.ZipFile('/home/mluser/ml-lab-source.zip') as archive:
    for item in archive.infolist():
        if item.is_dir(): continue
        name=Path(item.filename)
        if not name.parts or name.parts[0]!='ml-project' or '..' in name.parts: raise SystemExit('Invalid source path')
        relative=Path(*name.parts[1:])
        if '.git' in relative.parts: continue
        target=base/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.resolve().is_relative_to(base.resolve()): raise SystemExit('Source path escaped the project')
        data=archive.read(item)
        if target.is_file() and hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(data).digest(): continue
        temporary=target.with_name(target.name+'.labtmp')
        temporary.write_bytes(data)
        os.replace(temporary,target)
Path('/home/mluser/ml-lab-source.zip').unlink()
PY

step '4/9: Ubuntu packages, updates, Git and Docker'
if [[ ! -f ${vm_state}/system-installed ]]; then
    vm_admin 'sudo bash /home/mluser/ml-project/scripts/install_system.sh'
    touch "${vm_state}/system-installed"
fi
if vm_admin 'test -f /var/run/reboot-required'; then
    echo 'Rebooting only the Ubuntu guest after updates...'
    vm_admin 'sudo systemctl reboot' || true
    sleep 5
    wait_for_guest
fi
vm_admin 'sudo bash /home/mluser/ml-project/scripts/codespaces/tidy_services.sh'
vm_user 'id; groups; test "$(id -un)" = mluser; touch /home/mluser/.lab1-key-verified' > evidence/client/ssh-login-before.txt
vm_user 'if id -nG | tr " " "\n" | grep -Eq "^(sudo|docker|root)$"; then echo "mluser unexpectedly belongs to a privileged group" >&2; exit 1; fi'
sudo -n python3 scripts/codespaces/console_vm.py "${vm_state}/console.sock" --probe > evidence/client/console-proof.txt
vm_admin 'sudo bash /home/mluser/ml-project/scripts/protect_baseline.sh'

step '5/9: SSH protection and firewall inside the Ubuntu guest'
ssh -F "${vm_state}/ssh_config" -O check ml-lab > evidence/client/ssh-existing-session.txt 2>&1
if [[ ! -f ${vm_state}/hardening-confirmed ]]; then
    vm_admin 'sudo bash /home/mluser/ml-project/scripts/harden_vm.sh --key-login-verified'
fi
ssh -F "${vm_state}/ssh_config" -o ControlMaster=no -o ControlPath=none ml-lab \
    'id; groups; test "$(id -un)" = mluser' > evidence/client/ssh-login-after.txt
# Отказ root ожидаем. Условие if подавляет ERR trap для этой проверки;
# set +e отключает только errexit и не подавляет сам ERR trap.
if ssh -F "${vm_state}/ssh_config" -o ControlMaster=no -o ControlPath=none -l root ml-lab true \
    > evidence/client/root-login-denied.txt 2>&1; then
    root_code=0
else
    root_code=$?
fi
printf '%s\n' "${root_code}" > evidence/client/root-login.exitcode
if [[ ${root_code} -ne 255 ]] || ! grep -q 'Permission denied' evidence/client/root-login-denied.txt; then
    echo 'Root denial was not confirmed. The rollback timer remains active.' >&2
    exit 1
fi
if [[ ! -f ${vm_state}/hardening-confirmed ]]; then
    vm_admin 'sudo bash /home/mluser/ml-project/scripts/confirm_hardening.sh'
    touch "${vm_state}/hardening-confirmed"
fi
ssh -F "${vm_state}/ssh_config" -O check ml-lab >> evidence/client/ssh-existing-session.txt 2>&1

step '6/9: Python environment, dataset, Notebook, dependency audit'
vm_user 'cd /home/mluser/ml-project && ML_LAB_RESOLVE_DEPENDENCIES=1 bash scripts/setup_project.sh'
vm_user 'bash /home/mluser/ml-project/scripts/codespaces/start_jupyter_vm.sh'
vm_user 'bash -s' <<'SH'
set -e
cd /home/mluser/ml-project
if [[ ! -d .git ]]; then git init -b main; fi
git add .
if ! git diff --cached --quiet; then
    git -c user.name='Lab Automation' -c user.email='lab-automation@localhost' commit -m 'Record verified Ubuntu VM lab results'
fi
{
    id
    git log -1 --format='%h %s'
    git check-ignore -v .env .venv/example data/raw/SMSSpamCollection .labvm/client_key
    git status --short
} > evidence/vm/git-checks.log
SH

step '7/9: collecting actual security evidence'
vm_admin 'sudo bash /home/mluser/ml-project/scripts/collect_security.sh'
vm_admin 'sudo python3 /home/mluser/ml-project/scripts/codespaces/analyze_ports.py'
scp -F "${vm_state}/ssh_config" -r evidence/client ml-lab:/home/mluser/ml-project/evidence/
vm_user 'cd /home/mluser/ml-project && .venv/bin/python scripts/build_vm_report.py'
scp -F "${vm_state}/ssh_config" ml-lab:/home/mluser/ml-project/evidence/vm-results.tar.gz "${vm_state}/results.tar.gz"
python3 - "${vm_state}/results.tar.gz" "${project_root}" <<'PY'
import tarfile, sys
from pathlib import Path
archive_path,root=map(Path,sys.argv[1:])
root=root.resolve()
with tarfile.open(archive_path) as archive:
    if sum(member.size for member in archive.getmembers())>100*1024**2: raise SystemExit('Unexpected results size')
    for member in archive.getmembers():
        relative=Path(member.name)
        if relative.is_absolute() or '..' in relative.parts or member.issym() or member.islnk(): raise SystemExit('Unsafe results member')
        target=(root/relative).resolve()
        if not target.is_relative_to(root): raise SystemExit('Results path escaped the project')
        if member.isdir(): target.mkdir(parents=True,exist_ok=True)
        elif member.isfile():
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(member) as stream: target.write_bytes(stream.read())
PY

step '8/9: local Git checkpoint and result archive'
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then git init -b main; fi
python3 - "${vm_state}" <<'PY'
import subprocess,sys,zipfile,json
from pathlib import Path
state=Path(sys.argv[1]);root=Path.cwd()
files=[]
with zipfile.ZipFile(state/'project.zip') as archive:
    for name in archive.namelist():
        path=Path(name)
        if name.endswith('/') or path.parts[0]!='ml-project': continue
        rel=Path(*path.parts[1:])
        if rel.parts[:2] in [('data','raw'),('data','processed')] and rel.name!='.gitkeep': continue
        if rel.parts[0] in {'.git','evidence'}: continue
        if (root/rel).is_file(): files.append(str(rel))
files+=['docs/VM_REPORT.md','requirements.txt','notebooks/01_dataset_analysis.ipynb','evidence/dataset-profile.json']
subprocess.run(['git','add','--',*sorted(set(files))],check=True)
if subprocess.run(['git','diff','--cached','--quiet']).returncode:
    subprocess.run(['git','-c','user.name=Lab Automation','-c','user.email=lab-automation@localhost','commit','-m','Complete lab 1 on the Ubuntu QEMU/KVM VM'],check=True)
tracked=subprocess.check_output(['git','ls-files','-z']).decode().split('\0')
selected={Path(name) for name in tracked if name}
for folder in ['evidence/vm','evidence/client','data/raw']:
    selected.update(path.relative_to(root) for path in (root/folder).rglob('*') if path.is_file())
with zipfile.ZipFile(root/'lab1-results.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for relative in sorted(selected):
        if any(part in {'.git','.venv','.labvm','__pycache__'} for part in relative.parts): continue
        path=root/relative
        if path.is_file(): archive.write(path,'ml-project/'+relative.as_posix())
print('Prepared: lab1-results.zip')
PY

step '9/9: final status'
python3 - <<'PY'
import json
from pathlib import Path
status=json.loads(Path('evidence/vm/summary.json').read_text())
for name,passed in status['checks'].items(): print(('PASS: ' if passed else 'REVIEW: ')+name)
print('\nLAB_READY' if status['all_checks_passed'] else '\nLAB_FINISHED_WITH_REVIEW')
print('Report: docs/VM_REPORT.md')
print('Executed notebook: notebooks/01_dataset_analysis.ipynb')
print('Downloadable materials: lab1-results.zip')
print('The Git repository must still be published to your GitHub account to obtain the submission URL.')
PY
echo 'Ubuntu VM is still running. VM files and private keys are excluded from Git.'
