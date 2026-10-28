import json
from pathlib import Path

import pandas as pd

from src.splitting import prepare_splits


def test_splits_are_reproducible_and_normalized_duplicates_cannot_leak(tmp_path, monkeypatch):
    rows = [{'text': f'ordinary example message {i}', 'target': 'ham'} for i in range(80)]
    rows += [{'text': f'claim prize example {i}', 'target': 'spam'} for i in range(20)]
    rows += [{'text': '  ORDINARY   EXAMPLE MESSAGE 0 ', 'target': 'ham'}]
    rows += [{'text': 'bad\x00example', 'target': 'ham'}]
    fake = pd.DataFrame(rows)
    monkeypatch.setattr('src.splitting.load_dataset', lambda _: fake.copy())
    monkeypatch.setattr('src.splitting.read_manifest', lambda _: {'files': {'data/raw/SMSSpamCollection': {'sha256': 'a' * 64}}})
    (tmp_path / 'config').mkdir()
    source = Path(__file__).resolve().parents[1] / 'config/lab2.json'
    (tmp_path / 'config/lab2.json').write_bytes(source.read_bytes())
    first, split1, summary1 = prepare_splits(tmp_path)
    second, split2, summary2 = prepare_splits(tmp_path)
    assert split1 == split2
    assert summary1 == summary2
    assert first.equals(second)
    assert summary1['retained_records'] == 100
    assert summary1['removed_invalid_inputs'] == 1
    assert summary1['removed_normalized_duplicates'] == 1
    assert {name: len(ids) for name, ids in split1.items()} == {'train': 60, 'ci': 20, 'test': 20}
    groups = {name: set(first.iloc[ids]['normalized']) for name, ids in split1.items()}
    assert not groups['train'] & groups['ci']
    assert not groups['train'] & groups['test']
    assert not groups['ci'] & groups['test']
    assert all(first.iloc[ids]['target'].value_counts().to_dict() == {'ham': int(len(ids) * .8), 'spam': int(len(ids) * .2)} for ids in split1.values())
    private = json.loads((tmp_path / 'data/processed/lab2/split-indices.json').read_text())
    assert len(private['excluded_invalid_source_rows']) == 1
