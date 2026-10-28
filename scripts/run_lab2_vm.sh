#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ ${EUID} -ne 0 && $(id -un) == mluser && -d /run/systemd/system ]] || { echo 'Run as mluser inside the lab Ubuntu VM.' >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "${root}"
mkdir -p evidence/lab2/vm metrics figures/lab2
exec > >(tee evidence/lab2/vm/run.log) 2>&1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python -m pip check | tee evidence/lab2/vm/pip-check.txt
.venv/bin/python -m pip freeze > evidence/lab2/vm/requirements-observed.txt
cp evidence/lab2/vm/requirements-observed.txt requirements.txt
.venv/bin/python scripts/download_dataset.py
.venv/bin/python scripts/check_integrity.py --require-protected-baseline | tee evidence/lab2/vm/dataset-integrity.txt
.venv/bin/python - <<'PY'
from pathlib import Path
import datetime,getpass,json,os,platform,importlib.metadata
names=['scikit-learn','skops','pandas','numpy','pytest','bandit','jupyterlab','pip-audit','pip']
info={'user':getpass.getuser(),'uid':os.getuid(),'python':platform.python_version(),'packages':{name:importlib.metadata.version(name) for name in names},'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_commit':os.environ.get('ML_LAB2_SOURCE_COMMIT','unknown')}
Path('evidence/lab2/vm/environment.json').write_text(json.dumps(info,indent=2)+'\n')
print(json.dumps(info,indent=2))
PY
.venv/bin/python -m ipykernel install --user --name ml-lab --display-name 'Python (ml-lab)'
.venv/bin/python -m jupyter nbconvert --execute --to notebook --inplace \
    --ExecutePreprocessor.kernel_name=ml-lab --ExecutePreprocessor.timeout=180 notebooks/02_baseline_robustness.ipynb
.venv/bin/python - <<'PY'
from pathlib import Path
import getpass,nbformat
p=Path('notebooks/02_baseline_robustness.ipynb');n=nbformat.read(p,as_version=4)
if any(o.output_type=='error' for c in n.cells if c.cell_type=='code' for o in c.outputs):raise SystemExit('Notebook contains a failed cell')
n.metadata['validation']={'method':'Jupyter nbconvert --execute on the target Ubuntu VM','jupyter_kernel_start_verified':True,'execution_user':getpass.getuser()}
nbformat.validate(n);nbformat.write(n,p)
PY
.venv/bin/python -m pytest tests/ -q --junitxml=evidence/lab2/vm/tests.xml | tee evidence/lab2/vm/tests.txt
.venv/bin/python -m bandit -r src/ -f json -o evidence/lab2/vm/bandit.json > evidence/lab2/vm/bandit.txt 2>&1
printf '0\n' > evidence/lab2/vm/bandit.exitcode
if .venv/bin/python -m pip_audit --format=json --output evidence/lab2/vm/pip-audit.json > evidence/lab2/vm/pip-audit.stdout.txt 2> evidence/lab2/vm/pip-audit.txt; then
    printf '0\n' > evidence/lab2/vm/pip-audit.exitcode
else
    code=$?; printf '%s\n' "${code}" > evidence/lab2/vm/pip-audit.exitcode
    cat evidence/lab2/vm/pip-audit.txt >&2
    echo 'Dependency audit requires review; a clean audit is not claimed.' >&2
    exit "${code}"
fi
.venv/bin/python scripts/render_audit.py evidence/lab2/vm/pip-audit.json | tee evidence/lab2/vm/pip-audit-summary.txt
echo 'LAB2_ML_CHECKS_PASSED: external protection and runtime verification follow.'
