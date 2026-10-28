"""Единая точка предсказания для тестов, CLI и будущего API."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json

from src.artifacts import ArtifactError, MODEL_RELATIVE, ROOT, load_verified_model, preferred_reference
from src.preprocessing import InputPolicy, configured_policy, read_config, validate_payload


class SmsPredictor:
    def __init__(self, model, model_version: str = 'lab2-v1', policy: InputPolicy | None = None):
        self.model = model
        self.model_version = model_version
        self.policy = policy if policy is not None else InputPolicy()

    @classmethod
    def from_project(cls, root: Path = ROOT, reference: Path | None = None):
        baseline = reference if reference is not None else preferred_reference(root)
        model, record = load_verified_model(root / MODEL_RELATIVE, baseline)
        configuration = json.dumps(read_config(root), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if hashlib.sha256(configuration).hexdigest() != record.get('config_sha256'):
            raise ArtifactError('Inference configuration differs from the saved model reference')
        return cls(model, record['model_version'], configured_policy(root))

    def predict(self, payload: object) -> dict:
        normalized = validate_payload(payload, self.policy)
        label = str(self.model.predict([normalized])[0])
        if label not in {'ham', 'spam'}:
            raise ValueError('Model returned an unsupported class')
        return {'prediction': label, 'model_version': self.model_version}
