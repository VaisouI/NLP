"""Проверка модели до десериализации; skops без расширения списка доверия."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import sklearn
import skops.io as sio
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from src.preprocessing import NORMALIZATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
MODEL_RELATIVE = Path('models/lab2-v1/model.skops')
REFERENCE_RELATIVE = Path('security/model-manifest-lab2-v1.json')
PROTECTED_REFERENCE = Path('/var/lib/ml-lab/model-integrity/lab2-v1.json')
MAX_MODEL_BYTES = 20 * 1024 * 1024


class ArtifactError(ValueError):
    """Артефакт не загружается при ошибке хэша, версии или списка типов."""


def preferred_reference(root: Path = ROOT) -> Path:
    return PROTECTED_REFERENCE if PROTECTED_REFERENCE.is_file() else root / REFERENCE_RELATIVE


def read_model_manifest(reference: Path) -> dict:
    record = json.loads(Path(reference).read_text(encoding='utf-8'))
    if record.get('format') != 'skops' or record.get('model_version') != 'lab2-v1':
        raise ArtifactError('Unsupported model format or version')
    if not re.fullmatch(r'[0-9a-f]{64}', record.get('sha256', '')):
        raise ArtifactError('Invalid model SHA256 reference')
    if type(record.get('bytes')) is not int or not 0 < record['bytes'] <= MAX_MODEL_BYTES:
        raise ArtifactError('Invalid model size reference')
    if record.get('normalization_version') != NORMALIZATION_VERSION:
        raise ArtifactError('Incompatible preprocessing version')
    if record.get('sklearn_version') != sklearn.__version__:
        raise ArtifactError('scikit-learn version differs from the saved model environment')
    return record


def load_verified_model(model_path: Path, reference: Path) -> tuple[Pipeline, dict]:
    record = read_model_manifest(reference)
    with Path(model_path).open('rb') as stream:
        data = stream.read(MAX_MODEL_BYTES + 1)
    if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ArtifactError('Model integrity check failed; deserialization was not attempted')
    unknown = sio.get_untrusted_types(data=data)
    if unknown:
        raise ArtifactError('Model contains types outside the fixed skops trust policy')
    model = sio.loads(data, trusted=[])
    if type(model) is not Pipeline or list(model.named_steps) != ['tfidf', 'classifier']:
        raise ArtifactError('Unexpected model structure')
    if type(model.named_steps['tfidf']) is not TfidfVectorizer or type(model.named_steps['classifier']) is not LogisticRegression:
        raise ArtifactError('Unexpected model component types')
    if list(model.classes_) != ['ham', 'spam']:
        raise ArtifactError('Unexpected model classes')
    return model, record
