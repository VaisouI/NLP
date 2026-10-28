#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
[[ ${EUID} -ne 0 ]] || { echo 'Run as the unprivileged development user, not root.' >&2; exit 1; }
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "${project_root}"
mkdir -p evidence/vm evidence/windows
exec > >(tee evidence/vm/project-setup.log) 2>&1
date --iso-8601=seconds
id
groups
python3 -m venv .venv
source .venv/bin/activate
# Обновляем установщик до версии, зафиксированной при подготовке лабораторной.
if [[ ${ML_LAB_RESOLVE_DEPENDENCIES:-0} == 1 ]]; then
    # На новой VM фиксируем действительно доступные и установленные версии.
    if [[ ! -f docs/requirements-preparation.txt ]]; then
        cp requirements.txt docs/requirements-preparation.txt
    fi
    python -m pip install --disable-pip-version-check --upgrade pip
    python -m pip install --disable-pip-version-check -r requirements.in
    python -m pip freeze > requirements.txt
else
    python -m pip install --disable-pip-version-check pip==26.2.2
    python -m pip install --disable-pip-version-check -r requirements.txt
fi
python -m pip check | tee evidence/vm/pip-check.log
python -m pip freeze > evidence/vm/requirements-observed.txt
python -m pip --version
python scripts/download_dataset.py
python scripts/check_integrity.py --require-protected-baseline | tee evidence/vm/integrity.log
python scripts/tamper_demo.py | tee evidence/vm/tamper-demo.log
python -m unittest discover -s tests -v 2>&1 | tee evidence/vm/tests.log
python -m ipykernel install --user --name ml-lab --display-name 'Python (ml-lab)'
python -m jupyter nbconvert --execute --to notebook --inplace \
    --ExecutePreprocessor.kernel_name=ml-lab --ExecutePreprocessor.timeout=180 \
    notebooks/01_dataset_analysis.ipynb
python - <<'PY'
from pathlib import Path
import nbformat
path = Path('notebooks/01_dataset_analysis.ipynb')
notebook = nbformat.read(path, as_version=4)
notebook.metadata['validation'] = {
    'method': 'Jupyter nbconvert --execute on the target Ubuntu VM',
    'jupyter_kernel_start_verified': True,
}
nbformat.validate(notebook)
nbformat.write(notebook, path)
PY
set +e
python -m pip_audit --format=json --output evidence/vm/pip-audit.json 2> evidence/vm/pip-audit.log
audit_exit=$?
set -e
printf '%s\n' "${audit_exit}" > evidence/vm/pip-audit.exitcode
python scripts/render_audit.py evidence/vm/pip-audit.json | tee evidence/vm/pip-audit-summary.txt
# Не подменяем исходный lockfile. Сохраняем фактически установленный набор отдельно.
python -m pip freeze > evidence/vm/requirements-observed.txt
if [[ ${audit_exit} -ne 0 ]]; then
    echo 'AUDIT_REQUIRES_REVIEW: inspect the JSON/log before claiming a clean environment.' >&2
    exit "${audit_exit}"
fi
echo 'Project checks completed as the unprivileged user.'

