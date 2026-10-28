"""Загрузка исходных SMS без потери строк с кавычками или табуляцией."""
from __future__ import annotations

import unicodedata
from pathlib import Path

import pandas as pd

from src.integrity import ROOT, verify_dataset


def normalize_for_grouping(text: str) -> str:
    """Только ключ для поиска дубликатов; исходный текст не меняется."""
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def load_dataset(root: Path = ROOT, baseline: Path | None = None) -> pd.DataFrame:
    verify_dataset(root, baseline)
    path = root / 'data/raw/SMSSpamCollection'
    records = []
    for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        label, separator, text = line.partition('\t')
        if not separator or label not in {'ham', 'spam'} or not text.strip():
            raise ValueError(f'Некорректная запись в строке {line_number}')
        records.append({'target': label, 'text': text})
    return pd.DataFrame(records, columns=['target', 'text'])


def profile_dataset(df: pd.DataFrame) -> dict:
    counts = df['target'].value_counts().reindex(['ham', 'spam'], fill_value=0)
    normalized = df['text'].map(normalize_for_grouping)
    return {
        'records': len(df),
        'features_raw': ['text'],
        'target': 'target',
        'classes': {label: int(value) for label, value in counts.items()},
        'class_percent': {label: float(value / len(df) * 100) for label, value in counts.items()},
        'majority_to_minority_ratio': float(counts.max() / counts.min()),
        'majority_baseline_accuracy': float(counts.max() / len(df)),
        'missing_cells': int(df.isna().sum().sum()),
        'empty_texts': int(df['text'].str.strip().eq('').sum()),
        'duplicate_rows_excess': int(df.duplicated().sum()),
        'unique_rows': int(len(df.drop_duplicates())),
        'duplicate_texts_excess': int(df['text'].duplicated().sum()),
        'normalized_duplicate_texts_excess': int(normalized.duplicated().sum()),
        'exact_text_label_conflicts': int((df.groupby('text')['target'].nunique() > 1).sum()),
        'normalized_text_label_conflicts': int((df.groupby(normalized)['target'].nunique() > 1).sum()),
        'text_length_characters': {
            str(label): {str(k): float(v) for k, v in values.items()}
            for label, values in df.assign(length=df['text'].str.len()).groupby('target')['length'].describe().to_dict(orient='index').items()
        },
    }

