#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ ${CODESPACES:-} == true && ${EUID} -ne 0 ]] || { echo 'Run in the existing lab1 Codespace without sudo.' >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "${root}"
state="${root}/.labvm"
mkdir -p "${state}"
chmod 0700 "${state}"
exec > >(tee -a "${state}/lab2-launcher.log") 2>&1
stage=preflight
tunnel_active=false
on_error() {
    local code=$?
    trap - ERR
    if [[ ${tunnel_active} == true ]]; then
        if ssh -F "${state}/ssh_config" -O cancel -L 127.0.0.1:18888:127.0.0.1:8888 ml-lab >/dev/null 2>&1; then :; fi
    fi
    echo "LAB2_STOPPED: stage=${stage}, exit=${code}"
    echo 'Saved VM and original data are preserved. Log: .labvm/lab2-launcher.log'
    exit "${code}"
}
trap on_error ERR
step() { stage=$1; printf '\n===== %s =====\n' "${stage}"; }
source_commit=$(git rev-parse HEAD)
[[ ${source_commit} =~ ^[0-9a-f]{40}$ ]]
step '1/6: resume the saved Ubuntu VM'
bash scripts/codespaces/resume_lab_vm.sh "${state}"
admin() { ssh -F "${state}/ssh_config" ml-lab-admin "$@"; }
user() { ssh -F "${state}/ssh_config" ml-lab "$@"; }
step '2/6: copy reviewed source into the VM'
python3 - "${state}/lab2-source.zip" <<'PY'
from pathlib import Path
import subprocess,sys,zipfile
root=Path.cwd().resolve()
names=subprocess.check_output(['git','ls-files','-z']).decode().split('\0')
with zipfile.ZipFile(sys.argv[1],'w',zipfile.ZIP_DEFLATED) as archive:
    for name in names:
        if not name:continue
        rel=Path(name);path=root/rel
        if rel.parts[0] in {'.git','.venv','.labvm','evidence','models'}:continue
        if rel.parts[:2] in [('data','raw'),('data','processed')]:continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise SystemExit('Unsafe source path')
        if path.is_file():archive.write(path,'ml-project/'+rel.as_posix())
print('Source package prepared without private data or model artifacts.')
PY
scp -F "${state}/ssh_config" "${state}/lab2-source.zip" ml-lab:/home/mluser/lab2-source.zip
user 'python3 -' <<'PY'
from pathlib import Path
import os,zipfile
root=Path('/home/mluser/ml-project')
with zipfile.ZipFile('/home/mluser/lab2-source.zip') as archive:
    if sum(i.file_size for i in archive.infolist())>30*1024**2:raise SystemExit('Unexpected source package size')
    for item in archive.infolist():
        if item.is_dir():continue
        parts=Path(item.filename).parts
        if not parts or parts[0]!='ml-project' or '..' in parts:raise SystemExit('Unsafe source member')
        rel=Path(*parts[1:])
        if rel.parts[0] in {'.git','.venv','.labvm','models','evidence'}:raise SystemExit('Unexpected runtime member')
        target=root/rel
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):raise SystemExit('Unsafe source target')
        data=archive.read(item)
        if target.is_file() and target.read_bytes()==data:continue
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.lab2tmp');temporary.write_bytes(data);os.replace(temporary,target)
Path('/home/mluser/lab2-source.zip').unlink()
PY
step '3/6: train, evaluate, execute Notebook, tests and audits as mluser'
user "cd /home/mluser/ml-project && ML_LAB2_SOURCE_COMMIT=${source_commit} bash scripts/run_lab2_vm.sh"
step '4/6: protect the model reference and verify Jupyter'
admin 'sudo bash /home/mluser/ml-project/scripts/protect_lab2_model.sh'
user 'bash /home/mluser/ml-project/scripts/codespaces/start_jupyter_vm.sh'
user 'cd /home/mluser/ml-project && .venv/bin/python scripts/lab2_verify_runtime.py'
admin 'sudo python3 /home/mluser/ml-project/scripts/collect_lab2_security.py'
mkdir -p evidence/lab2/client
# Удаляем только прежнее перенаправление этого же SSH-клиента, если запуск прерывался.
if ssh -F "${state}/ssh_config" -O cancel -L 127.0.0.1:18888:127.0.0.1:8888 ml-lab >/dev/null 2>&1; then :; fi
ssh -F "${state}/ssh_config" -f -N -o ExitOnForwardFailure=yes \
    -L 127.0.0.1:18888:127.0.0.1:8888 ml-lab
tunnel_active=true
python3 - <<'PY'
from pathlib import Path
import json,urllib.request,urllib.error
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
try:status=opener.open('http://127.0.0.1:18888/api/status',timeout=5).status
except urllib.error.HTTPError as error:status=error.code
if status not in {302,401,403}:raise SystemExit('Jupyter tunnel did not enforce authentication')
record={'ssh_local_forward':'127.0.0.1:18888 -> VM 127.0.0.1:8888','unauthenticated_api_status':status,'token_in_report':False}
Path('evidence/lab2/client/jupyter-tunnel.json').write_text(json.dumps(record,indent=2)+'\n')
print('SSH loopback tunnel and Jupyter authentication: verified.')
PY
ssh -F "${state}/ssh_config" -O cancel -L 127.0.0.1:18888:127.0.0.1:8888 ml-lab
tunnel_active=false
scp -F "${state}/ssh_config" -r evidence/lab2/client ml-lab:/home/mluser/ml-project/evidence/lab2/
step '5/6: build the target VM report and collect private submission materials'
user 'cd /home/mluser/ml-project && .venv/bin/python scripts/build_lab2_report.py --target-vm && .venv/bin/python scripts/package_lab2.py'
scp -F "${state}/ssh_config" ml-lab:/home/mluser/ml-project/evidence/lab2-vm-results.tar.gz "${state}/lab2-results.tar.gz"
python3 - "${state}/lab2-results.tar.gz" <<'PY'
from pathlib import Path
import sys,tarfile
root=Path.cwd().resolve()
with tarfile.open(sys.argv[1]) as archive:
    if sum(m.size for m in archive.getmembers())>100*1024**2:raise SystemExit('Unexpected result archive size')
    for member in archive.getmembers():
        path=Path(member.name)
        if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():raise SystemExit('Unsafe result path')
        target=root/path
        if not target.resolve().is_relative_to(root):raise SystemExit('Result escaped the project')
        if member.isdir():target.mkdir(parents=True,exist_ok=True)
        elif member.isfile():
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(member) as stream:
                temporary=target.with_name(target.name+'.lab2tmp');temporary.write_bytes(stream.read());temporary.replace(target)
PY
step '6/6: save the reviewed results in Git'
git add -- README.md .gitignore requirements.txt requirements.in pytest.ini config src tests scripts \
    metrics security/model-manifest-lab2-v1.json notebooks/02_baseline_robustness.ipynb figures/lab2 docs/LAB2.md docs/LAB2_REPORT.md
if ! git diff --cached --quiet; then
    git -c user.name='Lab Automation' -c user.email='lab-automation@localhost' commit -m 'Complete lab 2 on the saved Ubuntu VM'
fi
python3 scripts/package_lab2.py --client-zip
if git push origin HEAD:main; then
    echo 'GitHub main: target VM results published.'
else
    echo 'LAB2_READY_PENDING_PUSH: results are saved; GitHub push needs attention.'
    exit 1
fi
python3 - <<'PY'
import json
from pathlib import Path
summary=json.loads(Path('evidence/lab2/vm/summary.json').read_text())
for name,passed in summary['checks'].items():print(('PASS: ' if passed else 'REVIEW: ')+name)
if not summary['all_checks_passed']:raise SystemExit('LAB2_REQUIRES_REVIEW')
print('\nLAB2_READY')
print('Report: docs/LAB2_REPORT.md')
print('Notebook: notebooks/02_baseline_robustness.ipynb')
print('Private submission: lab2-results.zip (contains model and data; do not publish it in public Git)')
PY
