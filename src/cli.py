"""Команды обучения, оценки и предсказания; ввод читается из stdin."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.artifacts import ArtifactError
from src.prediction import SmsPredictor
from src.preprocessing import InputValidationError
from src.robustness import run_robustness
from src.training import run_training
from src.validation_demo import run_validation_demo

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['train', 'evaluate', 'predict', 'robustness', 'validate'])
    args = parser.parse_args()
    try:
        if args.command == 'predict':
            # Ограничен и размер чтения stdin; для HTTP в ЛР4 добавится потоковый body limit.
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise InputValidationError('request_too_large', 'CLI JSON exceeds 65536 bytes')
            result = SmsPredictor.from_project(ROOT).predict(json.loads(raw))
        elif args.command == 'train':
            result = run_training(ROOT)
        elif args.command == 'evaluate':
            # Загружается сохранённый артефакт. Обучение при этой команде запрещено.
            if not (ROOT / 'models/lab2-v1/model.skops').is_file():
                raise ArtifactError('A saved model is required; run train first')
            result = run_training(ROOT)
        elif args.command == 'robustness':
            result = run_robustness(ROOT)
        else:
            result = run_validation_demo(ROOT)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (InputValidationError, ArtifactError, ValueError, OSError) as exc:
        print(json.dumps({'error': getattr(exc, 'code', 'operation_failed'), 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
