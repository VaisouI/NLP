#!/usr/bin/env python3
"""Скачивает строго зафиксированный архив UCI и проверяет его до распаковки."""
from __future__ import annotations

import io
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.integrity import ROOT, read_manifest, verify_dataset, verify_file


def main() -> None:
    manifest = read_manifest(ROOT / 'security/dataset-manifest.json')
    if all((ROOT / name).is_file() for name in manifest['files']):
        verify_dataset(ROOT, ROOT / 'security/dataset-manifest.json')
        print('Датасет уже существует; все эталонные SHA256 совпадают.')
        return
    # Повреждённый существующий файл не перезаписываем автоматически.
    for name, record in manifest['files'].items():
        if (ROOT / name).exists():
            verify_file(ROOT / name, record)
    url = manifest['source']['archive_url']
    request = urllib.request.Request(url, headers={'User-Agent': 'ml-lab1-reproducible/1.0'})
    with urllib.request.urlopen(request, timeout=60) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != 'https' or final.hostname != 'archive.ics.uci.edu':
            raise ValueError('Неожиданное перенаправление источника датасета')
        archive = response.read(5 * 1024 * 1024 + 1)
    if len(archive) > 5 * 1024 * 1024:
        raise ValueError('Архив превышает допустимый размер')
    with tempfile.TemporaryDirectory() as temporary:
        temp_root = Path(temporary)
        archive_path = temp_root / 'sms_spam_collection.zip'
        archive_path.write_bytes(archive)
        verify_file(archive_path, manifest['files']['data/raw/sms_spam_collection.zip'])
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            # Не используем extractall: берём только известные имена с ограничением размера.
            for name in ['SMSSpamCollection', 'readme']:
                info = zipped.getinfo(name)
                if info.file_size > 2 * 1024 * 1024:
                    raise ValueError('Слишком большой файл внутри архива')
                target = temp_root / name
                target.write_bytes(zipped.read(info))
                verify_file(target, manifest['files'][f'data/raw/{name}'])
        destination = ROOT / 'data/raw'
        destination.mkdir(parents=True, exist_ok=True)
        for source in temp_root.iterdir():
            target = destination / source.name
            if not target.exists():
                target.write_bytes(source.read_bytes())
    verify_dataset(ROOT, ROOT / 'security/dataset-manifest.json')
    print('Архив и исходные файлы UCI скачаны; SHA256 совпадают с сохранённым эталоном.')


if __name__ == '__main__':
    main()

