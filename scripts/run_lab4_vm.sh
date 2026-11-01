#!/usr/bin/env bash
# Выполняется от mluser; модель ЛР2 и защищённый эталон не перезаписываются.
set -Eeuo pipefail
umask 077
cd /home/mluser/ml-project
[[ $(id -un) == mluser && ${EUID} -ne 0 ]]
mkdir -p reports/lab4/vm reports/lab3
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
.venv/bin/python -m pip check > reports/lab4/vm/pip-check.txt
.venv/bin/python -m pip freeze > reports/lab4/vm/installed-requirements.txt
.venv/bin/python -m pytest tests/ -q --junitxml=reports/lab4/vm/pytest.xml | tee reports/lab4/vm/pytest.txt
.venv/bin/ruff check src/ tests/ --output-format=json > reports/lab4/vm/ruff.json
.venv/bin/python -m bandit -r src/ -f json -o reports/lab4/vm/bandit.json
.venv/bin/python scripts/ci/lab3.py audit
cp reports/lab3/pip-audit.json reports/lab4/vm/pip-audit.json
ML_MODEL_PATH=/home/mluser/ml-project/models/lab2-v1/model.skops \
ML_MODEL_REFERENCE=/var/lib/ml-lab/model-integrity/lab2-v1.json \
    .venv/bin/python scripts/ci/lab4.py local
if [[ ! -e .env.lab4 ]]; then
    .venv/bin/python scripts/create_api_env.py
fi
.venv/bin/python - <<'PY'
from pathlib import Path
from src.api_settings import Settings
secret=Path('.env.lab4')
if secret.is_symlink() or secret.stat().st_mode & 0o077:
    raise SystemExit('Runtime credential file must be a regular private file with mode 0600')
values=dict(line.split('=',1) for line in secret.read_text().splitlines())
if set(values)!={'ML_API_TOKEN','ML_METRICS_TOKEN'}:
    raise SystemExit('Unexpected runtime credential file schema')
Settings(api_token=values['ML_API_TOKEN'],metrics_token=values['ML_METRICS_TOKEN'])
print('Runtime credential file is valid and private. Values are omitted.')
PY
