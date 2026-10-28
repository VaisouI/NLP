#!/usr/bin/env bash
# Воспроизведение стенда из опубликованного репозитория без внешнего launcher-файла.
set -Eeuo pipefail
umask 077
[[ ${CODESPACES:-} == true ]] || { echo 'Run this script in your GitHub Codespace.' >&2; exit 1; }
[[ ${EUID} -ne 0 ]] || { echo 'Run without sudo; administration is delegated by run_lab.sh.' >&2; exit 1; }
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "${project_root}"
vm_state="${project_root}/.labvm"
mkdir -p "${vm_state}"
chmod 0700 "${vm_state}"
python3 scripts/download_dataset.py
python3 - "${vm_state}/project.zip" <<'PY'
import json, subprocess, sys, zipfile
from pathlib import Path
root = Path.cwd().resolve()
probe = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
if probe.returncode == 0 and Path(probe.stdout.strip()).resolve() == root:
    paths = {Path(name) for name in subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0') if name}
else:
    paths = {Path(name) for name in ['README.md', '.gitignore', '.gitattributes', 'requirements.txt', 'requirements.in']}
    for directory in ['scripts', 'src', 'tests', 'notebooks', 'security', 'docs', 'figures']:
        paths.update(p.relative_to(root) for p in (root / directory).rglob('*') if p.is_file())
    paths.update({Path('data/raw/.gitkeep'), Path('data/processed/.gitkeep'), Path('models/.gitkeep')})
manifest = json.loads((root / 'security/dataset-manifest.json').read_text())
paths.update(Path(name) for name in manifest['files'])
blocked_parts = {'.git', '.venv', '.labvm', '__pycache__', '.ipynb_checkpoints'}
blocked_names = {'lab1-codespaces.sh', 'lab1-finalize.sh', 'lab1-results.zip', 'client_key', 'host_key'}
with zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as archive:
    for relative in sorted(paths):
        if relative.is_absolute() or '..' in relative.parts:
            raise SystemExit('Unsafe source path')
        if any(part in blocked_parts for part in relative.parts) or relative.name in blocked_names:
            continue
        if relative.name.startswith('.env') or relative.suffix in {'.key', '.pem', '.pyc', '.qcow2', '.iso'}:
            continue
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise SystemExit('Source symlink is not permitted: ' + str(relative))
        if path.is_file():
            archive.write(path, 'ml-project/' + relative.as_posix())
print('Verified project package prepared for the guest VM.')
PY
# По умолчанию используется зафиксированное окружение из сдаваемого репозитория.
export ML_LAB_RESOLVE_DEPENDENCIES=${ML_LAB_RESOLVE_DEPENDENCIES:-0}
exec bash scripts/codespaces/run_lab.sh "${vm_state}"
