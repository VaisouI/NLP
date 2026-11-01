"""Small inference entry point: no pandas, notebook or training dependencies."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.prediction import SmsPredictor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--text', default='Can we meet for lunch tomorrow?')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    predictor = SmsPredictor.from_project(args.root)
    if args.self_test:
        examples = [('Can we meet for lunch tomorrow?', 'ham'),
                    ('Congratulations! You have won a free cash prize! Call now to claim your reward!', 'spam')]
        predictions = [predictor.predict({'text': text}) for text, _ in examples]
        if [item['prediction'] for item in predictions] != [label for _, label in examples]:
            raise ValueError('Saved model smoke predictions differ from expectations')
        print(json.dumps({'passed': True, 'model_version': predictor.model_version,
                          'predictions': predictions}))
    else:
        print(json.dumps(predictor.predict({'text': args.text})))


if __name__ == '__main__':
    main()
