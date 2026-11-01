"""Ограничения сервиса и runtime-секреты, не включаемые в repr."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from src.artifacts import ROOT, MODEL_RELATIVE, preferred_reference


@dataclass(frozen=True)
class Settings:
    api_token: str = field(repr=False)
    metrics_token: str = field(repr=False)
    model_path: Path = ROOT / MODEL_RELATIVE
    reference_path: Path = ROOT / 'security/model-manifest-lab2-v1.json'
    project_root: Path = ROOT
    max_body_bytes: int = 32768
    body_timeout_seconds: float = 3.0
    inference_timeout_seconds: float = 2.0
    startup_timeout_seconds: float = 20.0
    max_http_inflight: int = 16
    rate_limit: int = 10
    rate_period_seconds: float = 60.0
    invalid_auth_limit: int = 20
    invalid_auth_period_seconds: float = 60.0

    def __post_init__(self):
        for token in (self.api_token, self.metrics_token):
            if type(token) is not str or not 32 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token):
                raise ValueError('Two separate ASCII runtime tokens of 32–256 characters are required')
        if self.api_token == self.metrics_token:
            raise ValueError('Prediction and monitoring credentials must differ')
        for name, maximum in [('max_body_bytes', 65536), ('max_http_inflight', 64), ('rate_limit', 100), ('invalid_auth_limit', 100)]:
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('Invalid API resource limit')
        for name in ('body_timeout_seconds', 'inference_timeout_seconds', 'startup_timeout_seconds',
                     'rate_period_seconds', 'invalid_auth_period_seconds'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 120:
                raise ValueError('Invalid API time limit')

    @classmethod
    def from_env(cls, root: Path = ROOT) -> Settings:
        limits = json.loads((root / 'config/api.json').read_text(encoding='utf-8'))
        if 'ML_RATE_LIMIT' in os.environ:
            limits['rate_limit'] = int(os.environ['ML_RATE_LIMIT'])
        if 'ML_RATE_PERIOD_SECONDS' in os.environ:
            limits['rate_period_seconds'] = float(os.environ['ML_RATE_PERIOD_SECONDS'])
        return cls(api_token=os.environ.get('ML_API_TOKEN', ''), metrics_token=os.environ.get('ML_METRICS_TOKEN', ''),
                   project_root=root,
                   model_path=Path(os.environ.get('ML_MODEL_PATH', str(root / MODEL_RELATIVE))),
                   reference_path=Path(os.environ.get('ML_MODEL_REFERENCE', str(preferred_reference(root)))), **limits)
