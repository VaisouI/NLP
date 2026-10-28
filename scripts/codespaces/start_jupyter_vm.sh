#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -ne 0 ]] || exit 1
cd /home/mluser/ml-project
mkdir -p /home/mluser/.cache/ml-lab
chmod 0700 /home/mluser/.cache/ml-lab
if ! curl -s -o /dev/null --max-time 2 http://127.0.0.1:8888/lab; then
    nohup .venv/bin/python -m jupyter lab --no-browser --ip=127.0.0.1 --port=8888 \
        > /home/mluser/.cache/ml-lab/jupyter.log 2>&1 < /dev/null &
fi
for attempt in {1..30}; do
    http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8888/lab || true)
    if [[ ${http_code} == 200 || ${http_code} == 302 || ${http_code} == 303 ]]; then
        printf 'JUPYTER_LOOPBACK_OK HTTP=%s address=127.0.0.1:8888\n' "${http_code}" > evidence/vm/jupyter-health.txt
        exit 0
    fi
    sleep 1
done
echo 'Jupyter did not start; inspect /home/mluser/.cache/ml-lab/jupyter.log' >&2
exit 1
