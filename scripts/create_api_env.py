#!/usr/bin/env python3
"""Создаёт отдельные локальные секреты; значения никогда не печатаются."""
import argparse
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('.env.lab4'))
    args = parser.parse_args()
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write('ML_API_TOKEN=' + secrets.token_urlsafe(32) + '\n')
        stream.write('ML_METRICS_TOKEN=' + secrets.token_urlsafe(32) + '\n')
    print('Runtime credentials created with mode 0600. Values are not included in this output.')


if __name__ == '__main__':
    main()
