#!/usr/bin/env bash
# Продолжает работу на сохранённой Ubuntu VM. SSH/UFW и данные не меняет.
set -Eeuo pipefail
umask 077
[[ ${CODESPACES:-} == true && ${EUID} -ne 0 ]] || { echo 'Run from the existing lab Codespace without sudo.' >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "${root}"
state="${root}/.labvm"
[[ -f ${state}/ssh_config && -f ${state}/disk.qcow2 ]] || { echo 'The saved lab1–lab2 Ubuntu VM is required.' >&2; exit 1; }
exec > >(tee -a "${state}/lab4-launcher.log") 2>&1
source_commit=$(git rev-parse HEAD)
[[ ${source_commit} =~ ^[0-9a-f]{40}$ ]]
admin() { ssh -F "${state}/ssh_config" ml-lab-admin "$@"; }
user() { ssh -F "${state}/ssh_config" ml-lab "$@"; }
echo '1/5: Resume the saved Ubuntu VM.'
bash scripts/codespaces/resume_lab_vm.sh "${state}"
echo '2/5: Transfer reviewed source without private data, model or secrets.'
python3 - "${state}/lab4-source.zip" <<'PY'
from pathlib import Path
import subprocess,sys,zipfile
root=Path.cwd().resolve()
with zipfile.ZipFile(sys.argv[1],'w',zipfile.ZIP_DEFLATED) as archive:
    for name in subprocess.check_output(['git','ls-files','-z']).decode().split('\0'):
        if not name:continue
        rel=Path(name);path=root/rel
        if rel.parts[0] in {'.git','.venv','.labvm','.lab4','evidence','models','reports','artifacts'}:continue
        if rel.parts[:2] in [('data','raw'),('data','processed')]:continue
        if rel.name.startswith('.env') or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise SystemExit('Unsafe source member')
        if path.is_file():archive.write(path,rel.as_posix())
PY
scp -F "${state}/ssh_config" "${state}/lab4-source.zip" ml-lab:/home/mluser/lab4-source.zip
user 'python3 -' <<'PY'
from pathlib import Path
import os,zipfile
root=Path('/home/mluser/ml-project').resolve()
with zipfile.ZipFile('/home/mluser/lab4-source.zip') as archive:
    if sum(i.file_size for i in archive.infolist())>30*1024**2:raise SystemExit('Unexpected source package size')
    for item in archive.infolist():
        if item.is_dir():continue
        rel=Path(item.filename)
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:raise SystemExit('Unsafe source path')
        if rel.parts[0] in {'.git','.venv','.labvm','evidence','models','artifacts','reports'} or rel.name.startswith('.env'):
            raise SystemExit('Unexpected private source member')
        target=root/rel
        if target.is_symlink() or not target.resolve().is_relative_to(root):raise SystemExit('Unsafe source target')
        target.parent.mkdir(parents=True,exist_ok=True)
        data=archive.read(item)
        if target.is_file() and target.read_bytes()==data:continue
        temporary=target.with_name(target.name+'.lab4tmp');temporary.write_bytes(data);os.replace(temporary,target)
Path('/home/mluser/lab4-source.zip').unlink()
PY
echo '3/5: Verify the preserved lab2 model, tests, audit, live HTTP and detection as mluser.'
user "cd /home/mluser/ml-project && ML_LAB4_SOURCE_COMMIT=${source_commit} bash scripts/run_lab4_vm.sh"
echo '4/5: Start the loopback API as mluser in a bounded systemd service.'
admin 'sudo bash -s' <<'SH'
set -Eeuo pipefail
unit=/etc/systemd/system/ml-lab4-api.service
if [[ -e ${unit} ]] && ! head -n 1 "${unit}" | grep -Fxq '# Managed by the MLSecOps lab4 launcher'; then
    echo 'An unrelated unit already uses this name.' >&2
    exit 1
fi
cat > "${unit}" <<'UNIT'
# Managed by the MLSecOps lab4 launcher
[Unit]
Description=Lab4 protected SMS API
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=3
[Service]
Type=simple
User=mluser
Group=mluser
WorkingDirectory=/home/mluser/ml-project
EnvironmentFile=/home/mluser/ml-project/.env.lab4
Environment=PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
ExecStart=/home/mluser/ml-project/.venv/bin/python -m src.serve --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3
TimeoutStopSec=10
KillMode=control-group
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=512M
TasksMax=64
CPUQuota=100%
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl restart ml-lab4-api.service
systemctl is-active ml-lab4-api.service
SH
user 'cd /home/mluser/ml-project && .venv/bin/python -' <<'PY'
import json,time,urllib.request,urllib.error,os,hashlib
from pathlib import Path
for attempt in range(100):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2) as response:
            if response.status==200 and json.load(response)['status']=='healthy':break
    except (OSError,ValueError):pass
    time.sleep(.2)
else:raise SystemExit('Interactive API is not ready')
model=Path('models/lab2-v1/model.skops')
reference=Path('/var/lib/ml-lab/model-integrity/lab2-v1.json')
if os.access(reference,os.W_OK):raise SystemExit('Protected model reference is writable')
Path('reports/lab4/vm/interactive.json').write_text(json.dumps({'passed':True,'user':'mluser','euid':os.geteuid(),
    'health_status':200,'listen':'127.0.0.1:8000','protected_reference_writable':False,
    'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest()},indent=2)+'\n')
print('Interactive API and external protected model reference: verified.')
PY
echo '5/5: Open the SSH loopback tunnel and collect report files.'
python3 scripts/codespaces/lab4-fix-access.py --port 18000
scp -F "${state}/ssh_config" ml-lab:/home/mluser/ml-project/.env.lab4 "${state}/lab4.env"
chmod 0600 "${state}/lab4.env"
mkdir -p evidence/lab4/vm
scp -F "${state}/ssh_config" -r ml-lab:/home/mluser/ml-project/reports/lab4/. evidence/lab4/vm/
admin 'sudo journalctl -u ml-lab4-api.service --no-pager -o cat -n 40' > evidence/lab4/vm/interactive-service.txt
admin 'sudo ss -tulpn' > evidence/lab4/vm/listening-ports.txt
if command -v gh >/dev/null && [[ -n ${CODESPACE_NAME:-} ]]; then
    gh codespace ports visibility 18000:private --codespace "${CODESPACE_NAME}"
fi
python3 - <<'PY'
from pathlib import Path
import json,os,urllib.request,zipfile
with urllib.request.urlopen('http://127.0.0.1:18000/health',timeout=5) as response:
    if response.status!=200:raise SystemExit('SSH tunnel failed')
with zipfile.ZipFile('lab4-results.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for path in Path('evidence/lab4').rglob('*'):
        if path.is_file():archive.write(path,path.as_posix())
    for name in ('docs/LAB4.md','config/api.json','config/detection.json'):
        archive.write(name,name)
print('\nLAB4_READY: the saved lab2 model is served as mluser inside the Ubuntu VM.')
print('Open the private forwarded port 18000 in the Codespaces Ports tab.')
print('Runtime token file (private, excluded from Git): .labvm/lab4.env')
print('Reports archive: lab4-results.zip')
if os.environ.get('CODESPACE_NAME'):
    domain=os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN','app.github.dev')
    print('Page: https://'+os.environ['CODESPACE_NAME']+'-18000.'+domain+'/')
PY
