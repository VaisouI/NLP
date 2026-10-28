#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.integrity import PROTECTED_BASELINE, ROOT, default_baseline, verify_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description='Проверка файлов без перезаписи эталона')
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--require-protected-baseline', action='store_true')
    args = parser.parse_args()
    baseline = args.baseline or default_baseline()
    if args.require_protected_baseline:
        if baseline.resolve() != PROTECTED_BASELINE or not baseline.is_file():
            print('FAIL: защищённый эталон в /var/lib/ml-lab/integrity не установлен', file=sys.stderr)
            return 1
        stat = baseline.stat()
        parent_stat = baseline.parent.stat()
        if stat.st_uid != 0 or stat.st_mode & 0o022 or parent_stat.st_uid != 0 or parent_stat.st_mode & 0o022:
            print('FAIL: эталон или его каталог доступны на запись обычному пользователю', file=sys.stderr)
            return 1
    try:
        checked = verify_dataset(ROOT, baseline)
    except (ValueError, OSError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    print(f'Эталон: {baseline}')
    print('SHA256 проверяет неизменность относительно эталона, а не достоверность источника.')
    for name, digest in checked.items():
        print(f'OK {digest}  {name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

