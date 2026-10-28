#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -ne 0 ]] || { echo 'Use the development user.' >&2; exit 1; }
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "${project_root}"
source .venv/bin/activate
# Аутентификация Jupyter по умолчанию остаётся включённой.
exec python -m jupyter lab --no-browser --ip=127.0.0.1 --port=8888

