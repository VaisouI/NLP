#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || exit 1
[[ -f /var/lib/ml-lab/hardening-pending ]] || { echo 'No pending hardening run; check for rollback.' >&2; exit 1; }
rollback_unit=$(cat /var/lib/ml-lab/rollback-unit)
[[ ${rollback_unit} =~ ^ml-lab-rollback-[0-9]+-[0-9]+$ ]] || exit 1
systemctl stop "${rollback_unit}.timer"
rm /var/lib/ml-lab/hardening-pending
date --iso-8601=seconds > /var/log/ml-lab/hardening-confirmed.txt
echo 'Hardening confirmed after the client connection checks.'

