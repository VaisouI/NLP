#!/usr/bin/env python3
"""Негативная проверка на временной копии; оригинал и эталон не меняются."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.integrity import IntegrityError, ROOT, default_baseline, read_manifest, verify_file


def main() -> int:
    manifest = read_manifest(default_baseline())
    name = 'data/raw/SMSSpamCollection'
    source = ROOT / name
    record = manifest['files'][name]
    verify_file(source, record)
    with tempfile.TemporaryDirectory(prefix='ml-lab-tamper-') as temporary:
        copy = Path(temporary) / source.name
        copy.write_bytes(source.read_bytes())
        verify_file(copy, record)
        changed = bytearray(copy.read_bytes())
        changed[len(changed) // 2] ^= 1
        copy.write_bytes(changed)
        try:
            verify_file(copy, record)
        except IntegrityError:
            print('PASS: изменение одного байта временной копии обнаружено.')
        else:
            print('FAIL: изменение не обнаружено.', file=sys.stderr)
            return 1
    verify_file(source, record)
    print('PASS: оригинальный датасет и эталон сохранены без изменений.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

