"""Уникальные нормализованные тексты и воспроизводимые train/CI/test."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split

from src.dataset import load_dataset, profile_dataset
from src.integrity import read_manifest
from src.preprocessing import InputValidationError, configured_policy, normalize_text, read_config, validate_payload


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def prepare_splits(root: Path) -> tuple[object, dict, dict]:
    raw = load_dataset(root)
    profile = profile_dataset(raw)
    if profile['normalized_text_label_conflicts']:
        raise ValueError('Conflicting labels must be resolved before splitting')
    frame = raw.assign(source_row=np.arange(len(raw)), normalized=raw['text'].map(normalize_text))
    policy = configured_policy(root)
    exclusions = Counter()
    excluded_rows = []
    valid = []
    for idx, text in enumerate(frame['text']):
        try:
            validate_payload({'text': text}, policy)
            valid.append(idx)
        except InputValidationError as exc:
            exclusions[exc.code] += 1
            excluded_rows.append(idx)
    frame = frame.iloc[valid].copy()
    valid_before_deduplication = len(frame)
    frame = frame.drop_duplicates('normalized', keep='first').reset_index(drop=True)
    config = read_config(root)
    train_ci, test = train_test_split(
        np.arange(len(frame)), test_size=config['test_fraction'], random_state=config['seed'], stratify=frame['target'],
    )
    relative_ci = config['ci_fraction'] / (1.0 - config['test_fraction'])
    train, ci = train_test_split(
        train_ci, test_size=relative_ci, random_state=config['seed'], stratify=frame.iloc[train_ci]['target'],
    )
    indices = {'train': sorted(map(int, train)), 'ci': sorted(map(int, ci)), 'test': sorted(map(int, test))}
    groups = {name: set(frame.iloc[ids]['normalized']) for name, ids in indices.items()}
    if groups['train'] & groups['ci'] or groups['train'] & groups['test'] or groups['ci'] & groups['test']:
        raise ValueError('Normalized text leakage across splits')
    if sorted(sum(indices.values(), [])) != list(range(len(frame))):
        raise ValueError('The splits do not partition the retained dataset')
    source = read_manifest(root / 'security/dataset-manifest.json')['files']['data/raw/SMSSpamCollection']['sha256']
    private = {
        'schema_version': 1, 'source_sha256': source, 'seed': config['seed'],
        'method': 'first normalized occurrence; stratified 60/20/20 with no tuning on test',
        'source_rows': {name: frame.iloc[ids]['source_row'].tolist() for name, ids in indices.items()},
        'excluded_invalid_source_rows': excluded_rows,
    }
    split_sha = hashlib.sha256(canonical_json(private)).hexdigest()
    summary = {
        'source_sha256': source, 'dataset_version': 'uci-sms-' + source,
        'split_version': 'deduplicated-v1-seed42-60-20-20', 'split_sha256': split_sha,
        'raw_profile': profile, 'retained_records': len(frame),
        'retained_classes': {str(label): int(count) for label, count in frame['target'].value_counts().items()},
        'invalid_input_exclusions': dict(exclusions), 'removed_invalid_inputs': len(excluded_rows),
        'removed_normalized_duplicates': valid_before_deduplication - len(frame),
        'policy': 'Inputs rejected by the documented inference policy and repeated normalized texts excluded; no class balancing, imputation or label edits',
        'group_overlap_count': 0,
        'splits': {name: {'records': len(ids), 'classes': {str(k): int(v) for k, v in frame.iloc[ids]['target'].value_counts().items()}} for name, ids in indices.items()},
    }
    directory = root / 'data/processed/lab2'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    (directory / 'split-indices.json').write_bytes(canonical_json(private))
    return frame, indices, summary
