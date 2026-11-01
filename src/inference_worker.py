"""Закрытый stdin/stdout-протокол: модель загружается один раз на процесс."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.prediction import SmsPredictor


def emit(value: dict) -> None:
    print(json.dumps(value, allow_nan=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        predictor = SmsPredictor.from_files(args.model, args.reference, args.root)
    except Exception:
        # No paths, input data or exception text leave the worker.
        emit({'ready': False, 'error': 'model_load_failed'})
        return 1
    emit({'ready': True, 'model_version': predictor.model_version})
    while True:
        line = sys.stdin.buffer.readline(65537)
        if not line:
            return 0
        if len(line) > 65536 or not line.endswith(b'\n'):
            return 1
        try:
            emit(predictor.predict(json.loads(line)))
        except Exception:
            emit({'error': 'prediction_failed'})


if __name__ == '__main__':
    raise SystemExit(main())
