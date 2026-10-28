import json

import pytest

from src.training import frozen_json


def test_existing_baseline_is_never_replaced_by_different_candidate(tmp_path):
    path = tmp_path / 'baseline.json'
    first = {'value': .8, 'dataset_version': 'version-1'}
    frozen_json(path, first)
    before = path.read_bytes()
    frozen_json(path, first)
    with pytest.raises(ValueError, match='Existing baseline differs'):
        frozen_json(path, {'value': .7, 'dataset_version': 'version-1'})
    assert path.read_bytes() == before
    assert json.loads(path.read_text()) == first
