import hashlib
import json
from unittest.mock import Mock

import pytest
import sklearn
import skops.io as sio

from src.artifacts import ArtifactError, load_verified_model
from src.preprocessing import NORMALIZATION_VERSION, read_config
from src.training import build_pipeline


@pytest.fixture
def saved_model(tmp_path):
    config = read_config()
    config['tfidf']['min_df'] = 1
    model = build_pipeline(config)
    model.fit(['project meeting tomorrow', 'call me at lunch', 'free prize winner', 'claim free cash award'], ['ham', 'ham', 'spam', 'spam'])
    model_path = tmp_path / 'model.skops'
    sio.dump(model, model_path)
    payload = model_path.read_bytes()
    manifest = tmp_path / 'manifest.json'
    record = {'format': 'skops', 'model_version': 'lab2-v1', 'sha256': hashlib.sha256(payload).hexdigest(),
              'bytes': len(payload), 'normalization_version': NORMALIZATION_VERSION, 'sklearn_version': sklearn.__version__}
    manifest.write_text(json.dumps(record))
    return model, model_path, manifest


def test_saved_model_loads_and_retains_predictions(saved_model):
    original, path, reference = saved_model
    loaded, _ = load_verified_model(path, reference)
    texts = ['free prize', 'project meeting']
    assert loaded.predict(texts).tolist() == original.predict(texts).tolist()


def test_tampered_model_is_rejected_before_deserialization(saved_model, monkeypatch):
    _, path, reference = saved_model
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(raw)
    inspect = Mock()
    monkeypatch.setattr('src.artifacts.sio.get_untrusted_types', inspect)
    with pytest.raises(ArtifactError, match='integrity'):
        load_verified_model(path, reference)
    inspect.assert_not_called()


def test_unknown_skops_types_are_not_automatically_trusted(saved_model, monkeypatch):
    _, path, reference = saved_model
    construct = Mock()
    monkeypatch.setattr('src.artifacts.sio.get_untrusted_types', lambda **_: ['unreviewed.Example'])
    monkeypatch.setattr('src.artifacts.sio.loads', construct)
    with pytest.raises(ArtifactError, match='trust policy'):
        load_verified_model(path, reference)
    construct.assert_not_called()


def test_incompatible_library_version_is_rejected(saved_model):
    _, path, reference = saved_model
    record = json.loads(reference.read_text())
    record['sklearn_version'] = '0.0.0'
    reference.write_text(json.dumps(record))
    with pytest.raises(ArtifactError, match='version'):
        load_verified_model(path, reference)


def test_vectorizer_does_not_learn_from_prediction_inputs(saved_model):
    _, path, reference = saved_model
    model, _ = load_verified_model(path, reference)
    before = dict(model.named_steps['tfidf'].vocabulary_)
    vector = model.named_steps['tfidf'].transform(['neverobserveduniquetesttoken'])
    assert vector.shape == (1, len(before))
    assert vector.nnz == 0
    assert model.named_steps['tfidf'].vocabulary_ == before
