"""Одинаковая нормализация для обучения, оценки и предсказания."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

NORMALIZATION_VERSION = 'nfkc-casefold-whitespace-v1'
ROOT = Path(__file__).resolve().parents[1]


class InputValidationError(ValueError):
    """Контролируемый отказ до вызова модели; текст запроса не включается."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class InputPolicy:
    max_characters: int = 4096
    max_utf8_bytes: int = 16384

    def __post_init__(self):
        for value in (self.max_characters, self.max_utf8_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError('Input limits must be positive integers')


def read_config(root: Path = ROOT) -> dict:
    return json.loads((root / 'config/lab2.json').read_text(encoding='utf-8'))


def configured_policy(root: Path = ROOT) -> InputPolicy:
    config = read_config(root)['input_policy']
    return InputPolicy(config['max_characters'], config['max_utf8_bytes'])


def normalize_text(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def validate_payload(payload: object, policy: InputPolicy) -> str:
    """Вход — ровно один JSON-подобный объект {text: str}; не batch."""
    if type(payload) is not dict:
        raise InputValidationError('invalid_structure', 'Expected an object with one text field')
    if set(payload) != {'text'}:
        raise InputValidationError('invalid_fields', 'Exactly the text field is required')
    text = payload['text']
    if type(text) is not str:
        raise InputValidationError('invalid_type', 'text must be a string; null and numeric values are rejected')
    if len(text) > policy.max_characters:
        raise InputValidationError('text_too_long', 'Text exceeds the character limit')
    try:
        encoded = text.encode('utf-8', errors='strict')
    except UnicodeEncodeError as exc:
        raise InputValidationError('invalid_unicode', 'Text must be valid UTF-8 Unicode') from exc
    if len(encoded) > policy.max_utf8_bytes:
        raise InputValidationError('text_too_large', 'Text exceeds the UTF-8 byte limit')
    if any(unicodedata.category(char) == 'Cc' and not char.isspace() for char in text):
        raise InputValidationError('control_character', 'Unsupported control character')
    normalized = normalize_text(text)
    if not normalized:
        raise InputValidationError('empty_text', 'Text must contain non-whitespace characters')
    if len(normalized) > policy.max_characters or len(normalized.encode('utf-8')) > policy.max_utf8_bytes:
        raise InputValidationError('normalized_too_large', 'Normalized text exceeds the configured limit')
    return normalized
