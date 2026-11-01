#!/usr/bin/env bash
set -Eeuo pipefail
readonly version=0.76.1
readonly expected_sha=c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0
task_tmp=$(mktemp -d)
trap 'rm -rf -- "$task_tmp"' EXIT
curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --max-time 120 \
  "https://github.com/aquasecurity/trivy/releases/download/v${version}/trivy_${version}_Linux-64bit.tar.gz" \
  --output "$task_tmp/trivy.tar.gz"
printf '%s  %s\n' "$expected_sha" "$task_tmp/trivy.tar.gz" | sha256sum --check --strict
tar --no-same-owner -xzf "$task_tmp/trivy.tar.gz" -C "$task_tmp" trivy
mkdir -p "$HOME/.local/bin"
install -m 0755 "$task_tmp/trivy" "$HOME/.local/bin/trivy"
export PATH="$HOME/.local/bin:$PATH"
if [[ -n ${GITHUB_PATH:-} ]]; then
  printf '%s\n' "$HOME/.local/bin" >> "$GITHUB_PATH"
fi
trivy --version
