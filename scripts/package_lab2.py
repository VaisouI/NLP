#!/usr/bin/env python3
"""Приватные материалы преподавателю; файл архива исключён из Git."""
from pathlib import Path
import argparse
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def result_files():
    files = set()
    for folder in ['metrics', 'figures/lab2', 'evidence/lab2/vm', 'evidence/lab2/client', 'models/lab2-v1', 'data/raw', 'data/processed/lab2']:
        files.update(path.relative_to(ROOT) for path in (ROOT/folder).rglob('*') if path.is_file())
    files.update(Path(name) for name in ['requirements.txt','docs/LAB2_REPORT.md','notebooks/02_baseline_robustness.ipynb','security/model-manifest-lab2-v1.json'])
    for rel in files:
        path=ROOT/rel
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):raise SystemExit('Unsafe result source')
    return {rel for rel in files if (ROOT/rel).is_file()}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--client-zip',action='store_true');args=parser.parse_args()
    files=result_files()
    if args.client_zip:
        tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
        files.update(Path(name) for name in tracked if name)
        with zipfile.ZipFile(ROOT/'lab2-results.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for rel in sorted(files):
                if any(part in {'.git','.venv','.labvm','__pycache__','.ipynb_checkpoints'} for part in rel.parts):continue
                if rel.name.startswith('.env') or rel.name in {'lab1-codespaces.sh','lab1-finalize.sh','lab2-codespaces.sh','lab1-results.zip','lab2-results.zip','client_key','host_key'} or rel.suffix in {'.pem','.key','.iso','.qcow2','.pyc'}:continue
                path=ROOT/rel
                if path.is_symlink() or not path.resolve().is_relative_to(ROOT):raise SystemExit('Unsafe submission source')
                if path.is_file():archive.write(path,'ml-project/'+rel.as_posix())
        print('Private submission: lab2-results.zip; contains data and model, excluded from public Git.')
    else:
        with tarfile.open(ROOT/'evidence/lab2-vm-results.tar.gz','w:gz') as archive:
            for rel in sorted(files):archive.add(ROOT/rel,arcname=rel.as_posix(),recursive=False)
        print('Private VM results packaged.')


if __name__ == '__main__':
    main()
