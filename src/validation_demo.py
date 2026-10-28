"""Реальные позитивные и негативные вызовы одной функции предсказания."""
from __future__ import annotations

from pathlib import Path

from src.prediction import SmsPredictor
from src.preprocessing import InputPolicy, InputValidationError
from src.training import write_json


class CountingModel:
    def __init__(self, model):
        self.model = model
        self.calls = 0

    def predict(self, values):
        self.calls += 1
        return self.model.predict(values)


def run_validation_demo(root: Path) -> list[dict]:
    loaded = SmsPredictor.from_project(root)
    counter = CountingModel(loaded.model)
    service = SmsPredictor(counter, loaded.model_version, InputPolicy(max_characters=64, max_utf8_bytes=96))
    cases = [
        ('valid synthetic SMS', {'text': 'Project lab2 meeting tomorrow at noon'}, None),
        ('not an object', 'hello', 'invalid_structure'),
        ('missing text', {}, 'invalid_fields'),
        ('extra field', {'text': 'hello', 'extra': 1}, 'invalid_fields'),
        ('wrong text type', {'text': 42}, 'invalid_type'),
        ('null', {'text': None}, 'invalid_type'),
        ('NaN', {'text': float('nan')}, 'invalid_type'),
        ('Inf', {'text': float('inf')}, 'invalid_type'),
        ('empty', {'text': ' \t\n'}, 'empty_text'),
        ('character limit 65 > 64', {'text': 'x' * 65}, 'text_too_long'),
        ('UTF-8 byte limit 98 > 96', {'text': 'я' * 49}, 'text_too_large'),
        ('normalization expansion', {'text': '\ufb03' * 22}, 'normalized_too_large'),
        ('control character', {'text': 'hello\x00world'}, 'control_character'),
        ('invalid Unicode surrogate', {'text': '\ud800'}, 'invalid_unicode'),
    ]
    results = []
    for name, payload, expected in cases:
        before = counter.calls
        response = None
        actual = None
        try:
            response = service.predict(payload)
        except InputValidationError as exc:
            actual = exc.code
        calls = counter.calls - before
        passed = (actual == expected and calls == (1 if expected is None else 0)
                  and (expected is not None or response['prediction'] in {'ham', 'spam'}))
        results.append({'case': name, 'expected': expected or 'valid prediction',
                        'actual': actual or response, 'model_calls': calls, 'passed': passed})
        if not passed:
            raise ValueError('Unexpected validation behavior: ' + name)
    write_json(root / 'metrics/validation-cases.json', results)
    return results
