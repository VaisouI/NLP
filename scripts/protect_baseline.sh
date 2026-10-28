#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run as the VM administrator.' >&2; exit 1; }
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "${project_root}"
sha256sum --check security/SHA256SUMS
install -d -o root -g root -m 0755 /var/lib/ml-lab /var/lib/ml-lab/integrity
for name in dataset-manifest.json SHA256SUMS; do
    target="/var/lib/ml-lab/integrity/${name}"
    if [[ -e ${target} ]]; then
        cmp -s "security/${name}" "${target}" || { echo "Existing baseline differs: ${target}; refusing replacement." >&2; exit 1; }
    else
        install -o root -g root -m 0444 "security/${name}" "${target}"
    fi
done
chmod 0444 data/raw/SMSSpamCollection data/raw/sms_spam_collection.zip data/raw/readme
stat -c '%U %G %a %n' /var/lib/ml-lab/integrity /var/lib/ml-lab/integrity/*
echo 'The reference is readable but not writable by mluser. It is outside the project.'

