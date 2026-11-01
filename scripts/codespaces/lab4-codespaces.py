#!/usr/bin/env python3
"""Однокомандный запуск ЛР4 в сохранённом Codespace; только стандартная библиотека."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

REVIEWED_COMMIT = '76ee09ba7a100e945ec9f2f9681469ed5b8228b3'
CRITICAL_PATHS = ['src', 'scripts', 'config', 'tests', 'security', 'metrics', 'requirements.txt',
                  'requirements-runtime.txt', 'Dockerfile', '.dockerignore', '.github/workflows/ci.yml',
                  'pytest.ini', 'ruff.toml', 'static']


def git(*args, cwd=None, check=True):
    return subprocess.run(['git', *args], cwd=cwd, check=check, text=True, capture_output=True)


def main() -> int:
    if os.environ.get('CODESPACES') != 'true' or os.geteuid() == 0:
        print('Запустите этот файл в терминале существующего GitHub Codespace без sudo.')
        return 1
    root = Path(git('rev-parse', '--show-toplevel').stdout.strip()).resolve()
    remote = git('remote', 'get-url', 'origin', cwd=root).stdout.strip()
    if remote.startswith('git@github.com:'):
        repository = remote.removeprefix('git@github.com:').removesuffix('.git')
    else:
        parsed = urlparse(remote)
        repository = parsed.path.strip('/').removesuffix('.git')
        if parsed.scheme != 'https' or parsed.hostname != 'github.com' or parsed.username or parsed.password:
            raise ValueError('Unexpected repository origin')
    if repository.lower() != 'vaisoui/nlp':
        raise ValueError('Run this launcher inside the VaisouI/NLP project')
    if git('status', '--porcelain', '--untracked-files=no', cwd=root).stdout.strip():
        print('Есть незакоммиченные изменения. Они сохранены; launcher не будет их затирать.')
        return 1
    if not all((root / '.labvm' / name).is_file() for name in ('disk.qcow2', 'ssh_config')):
        print('Не найдена сохранённая .labvm/ ЛР1–ЛР2. Исходные файлы не изменены.')
        return 1
    print('Получаю зафиксированную версию ЛР4 из того же репозитория…', flush=True)
    git('fetch', '--no-tags', 'origin', REVIEWED_COMMIT, cwd=root)
    head = git('rev-parse', 'HEAD', cwd=root).stdout.strip()
    if head != REVIEWED_COMMIT:
        if git('merge-base', '--is-ancestor', head, REVIEWED_COMMIT, cwd=root, check=False).returncode == 0:
            git('merge', '--ff-only', REVIEWED_COMMIT, cwd=root)
        elif git('merge-base', '--is-ancestor', REVIEWED_COMMIT, head, cwd=root, check=False).returncode != 0:
            raise ValueError('The local branch diverged; no reset or deletion was performed')
    # Later documentation-only commits are allowed; changed executable sources are not.
    paths = [name for name in CRITICAL_PATHS if name != 'scripts']
    scripts = git('ls-tree', '-r', '--name-only', REVIEWED_COMMIT, '--', 'scripts', cwd=root).stdout.splitlines()
    paths.extend(scripts)
    if git('diff', '--quiet', REVIEWED_COMMIT, '--', *paths, cwd=root, check=False).returncode != 0:
        raise ValueError('Executable files differ from the reviewed snapshot; existing files were preserved')
    print('Код проверен. Запускаю проверки и API на сохранённой Ubuntu VM…', flush=True)
    subprocess.run(['bash', str(root / 'scripts/codespaces/run_lab4.sh')], cwd=root, check=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError):
        print('ЛР4 остановлена. Существующие данные, модель и диск VM сохранены. Проверьте последний этап в терминале.')
        raise SystemExit(1)
