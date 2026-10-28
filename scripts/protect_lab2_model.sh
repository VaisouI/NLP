#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 && -d /run/systemd/system ]] || { echo 'Run as administrator inside the lab VM.' >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
python3 - "${root}" <<'PY'
from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1]);record=json.loads((root/'security/model-manifest-lab2-v1.json').read_text())
path=root/'models/lab2-v1/model.skops'
if path.is_symlink() or not path.resolve().is_relative_to(root):raise SystemExit('Unexpected model path')
with path.open('rb') as stream:data=stream.read(20*1024**2+1)
if len(data)>20*1024**2 or len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256']:
    raise SystemExit('Model SHA256 mismatch; refusing to establish reference')
print('Model SHA256:',record['sha256'])
PY
install -d -o root -g root -m 0755 /var/lib/ml-lab/model-integrity
target=/var/lib/ml-lab/model-integrity/lab2-v1.json
if [[ -f ${target} ]]; then
    cmp -s "${root}/security/model-manifest-lab2-v1.json" "${target}" || { echo 'Protected model reference differs; refusing replacement.' >&2; exit 1; }
else
    install -o root -g root -m 0444 "${root}/security/model-manifest-lab2-v1.json" "${target}"
fi
chmod 0750 /home/mluser "${root}"
chmod 0700 "${root}/models" "${root}/models/lab2-v1" "${root}/data/raw" "${root}/data/processed"
chmod 0400 "${root}/models/lab2-v1/model.skops" "${root}/data/raw/SMSSpamCollection" "${root}/data/raw/sms_spam_collection.zip" "${root}/data/raw/readme"
stat -c '%U %G %a %n' "${target}" "${root}/models" "${root}/models/lab2-v1/model.skops" "${root}/data/raw"
