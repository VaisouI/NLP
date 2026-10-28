"""Проверка сохранённого эталона; функция проверки никогда не обновляет эталон."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_BASELINE = Path('/var/lib/ml-lab/integrity/dataset-manifest.json')


class IntegrityError(ValueError):
    """Данные отсутствуют, изменены либо эталон имеет недопустимый формат."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict:
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    if manifest.get('algorithm') != 'SHA256' or not manifest.get('files'):
        raise IntegrityError('Некорректный формат эталона SHA256')
    for name, record in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise IntegrityError(f'Недопустимый путь в эталоне: {name}')
        if not re.fullmatch(r'[0-9a-f]{64}', record.get('sha256', '')):
            raise IntegrityError(f'Некорректный SHA256 для {name}')
        size = record.get('bytes')
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise IntegrityError(f'Некорректный размер для {name}')
    return manifest


def default_baseline() -> Path:
    return PROTECTED_BASELINE if PROTECTED_BASELINE.exists() else ROOT / 'security/dataset-manifest.json'


def verify_file(path: Path, record: dict) -> str:
    path = Path(path)
    if not path.is_file():
        raise IntegrityError(f'Файл отсутствует: {path}')
    digest = sha256_file(path)
    if digest != record['sha256'] or path.stat().st_size != record['bytes']:
        raise IntegrityError(f'Нарушение целостности: {path.name}; SHA256={digest}')
    return digest


def verify_dataset(root: Path = ROOT, baseline: Path | None = None) -> dict[str, str]:
    baseline = Path(baseline) if baseline is not None else default_baseline()
    manifest = read_manifest(baseline)
    root = Path(root).resolve()
    checked = {}
    for name, record in manifest['files'].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise IntegrityError(f'Путь выходит за пределы проекта: {name}')
        checked[name] = verify_file(path, record)
    return checked

