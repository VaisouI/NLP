#!/usr/bin/env python3
"""Отдельный постоянный SSH-туннель к уже работающему API. Стандартная библиотека."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


class AccessError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def health(port: int) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(f'http://127.0.0.1:{port}/health', timeout=3) as response:
        data = response.read(2049)
        if response.status != 200 or len(data) > 2048:
            raise AccessError('API не готов к запросам.')
    result = json.loads(data)
    if result != {'status': 'healthy', 'model_version': 'lab2-v1'}:
        raise AccessError('Получен неожиданный ответ /health.')
    return result


def run_ssh(config: Path, *options: str, detached: bool = False):
    output = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL} if detached else {'capture_output': True}
    return subprocess.run(['ssh', '-F', str(config), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                           *options, 'ml-lab'], check=False, text=True, timeout=15, **output)


def control_socket(state: Path, port: int) -> Path:
    identifier = hashlib.sha256((str(state.resolve()) + ':' + str(port)).encode()).hexdigest()[:12]
    directory = Path(tempfile.gettempdir()) / f'ml-lab4-{os.getuid()}-{identifier}'
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise AccessError('Каталог управления туннелем имеет небезопасные права.')
    return directory / 'control'


def ensure_tunnel(state: Path, port: int) -> tuple[Path, bool]:
    """Явный transport-only master не наследует таймер общего ControlPersist."""
    config = state / 'ssh_config'
    if not config.is_file() or not 1024 <= port <= 65535:
        raise AccessError('Нужна существующая .labvm/ssh_config и непривилегированный порт.')
    control = control_socket(state, port)
    if run_ssh(config, '-S', str(control), '-O', 'check').returncode == 0:
        try:
            health(port)
            return control, False
        except (OSError, ValueError, AccessError):
            if run_ssh(config, '-S', str(control), '-O', 'exit').returncode != 0:
                raise AccessError('Не удалось остановить собственный прежний туннель.')
            time.sleep(.1)
    # Cancel only the exact old forwarding managed by the lab launcher, not other SSH sessions.
    run_ssh(config, '-O', 'cancel', '-L', f'127.0.0.1:{port}:127.0.0.1:8000')
    if control.exists() or control.is_symlink():
        info = control.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise AccessError('Неожиданный файл вместо управляющего сокета.')
        control.unlink()
    started = run_ssh(config, '-M', '-S', str(control), '-o', 'ControlMaster=yes', '-o', 'ControlPersist=no',
                      '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                      '-o', 'ExitOnForwardFailure=yes', '-f', '-N',
                      '-L', f'127.0.0.1:{port}:127.0.0.1:8000', detached=True)
    if started.returncode != 0:
        raise AccessError(f'Не удалось открыть SSH-туннель. Проверь доступ к VM и свободен ли порт {port}.')
    try:
        result = health(port)
    except (OSError, ValueError, AccessError) as exc:
        raise AccessError('Туннель создан, но API не готов. Требуется проверить ml-lab4-api.service на VM.') from exc
    if result['status'] != 'healthy':
        raise AccessError('API не готов.')
    return control, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18001)
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    if os.environ.get('CODESPACES') != 'true' or os.geteuid() == 0:
        raise AccessError('Запусти файл в корне прежнего Codespace без sudo.')
    state = Path.cwd() / '.labvm'
    if not (state / 'ssh_config').is_file():
        raise AccessError('В текущем каталоге не найдена .labvm/ssh_config.')
    if not 1024 <= args.port <= 65535:
        raise AccessError('Недопустимый номер порта.')
    if args.stop:
        result = run_ssh(state / 'ssh_config', '-S', str(control_socket(state, args.port)), '-O', 'exit')
        if result.returncode != 0:
            raise AccessError('Этот туннель не запущен.')
        print('Туннель остановлен. API на VM продолжает работать.')
        return 0
    control, created = ensure_tunnel(state, args.port)
    if os.environ.get('CODESPACE_NAME') and shutil.which('gh'):
        result = subprocess.run(['gh', 'codespace', 'ports', 'visibility', f'{args.port}:private', '--codespace',
                                 os.environ['CODESPACE_NAME']], check=False, timeout=20)
        if result.returncode != 0:
            print('Выбери видимость Private вручную во вкладке «Порты».')
    print('API: /health = 200, модель lab2-v1 готова.')
    print('SSH-туннель: ' + ('создан отдельно от общего соединения.' if created else 'уже работает.'))
    print(f'Вкладка «Порты» → добавь {args.port} → Private → протокол HTTP → открыть в браузере.')
    print('Внешняя ссылка GitHub остаётся HTTPS. API-токен хранится в прежнем .labvm/lab4.env.')
    if os.environ.get('CODESPACE_NAME'):
        domain = os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'app.github.dev')
        print('Страница: https://' + os.environ['CODESPACE_NAME'] + f'-{args.port}.' + domain + '/')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError, AccessError) as exc:
        print('Доступ пока не восстановлен: ' + (str(exc) if isinstance(exc, AccessError) else type(exc).__name__))
        raise SystemExit(1)
