"""Ограниченный эксперимент на 20 SMS; исходные данные не редактируются."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from src.ml_metrics import classification_metrics
from src.prediction import SmsPredictor
from src.preprocessing import normalize_text, read_config
from src.splitting import prepare_splits
from src.training import write_json


def add_typos(text: str, maximum: int = 3) -> str:
    replacements = 0

    def change(match):
        nonlocal replacements
        word = match.group(0)
        if replacements < maximum and word[1] != word[2]:
            replacements += 1
            return word[0] + word[2] + word[1] + word[3:]
        return word

    return re.sub(r'[A-Za-z]{4,}', change, text)


def run_robustness(root: Path) -> dict:
    frame, splits, _ = prepare_splits(root)
    predictor = SmsPredictor.from_project(root)
    config = read_config(root)
    test = frame.iloc[splits['test']]
    rng = np.random.default_rng(config['seed'])
    sampled = []
    for label in ['ham', 'spam']:
        selected = rng.choice(test.index[test['target'].eq(label)], config['robustness']['samples_per_class'], replace=False)
        sampled.extend(map(int, selected))
    subset = frame.loc[sorted(sampled)]
    truth = subset['target'].tolist()
    original_texts = subset['text'].tolist()
    original = [predictor.predict({'text': text})['prediction'] for text in original_texts]
    original_scores = predictor.model.decision_function([normalize_text(text) for text in original_texts])
    transformations = {
        'case_and_whitespace': lambda text: '  \n' + '   '.join(text.upper().split()) + '\t ',
        'typos': lambda text: add_typos(text, config['robustness']['max_typo_tokens']),
    }
    result = {
        'samples': len(subset), 'classes': {str(k): int(v) for k, v in subset['target'].value_counts().items()},
        'seed': config['seed'], 'original_metrics': classification_metrics(truth, original),
        'selection': '10 examples per class from final test; no model or threshold changes after observation',
        'variants': {}, 'limitations': 'Small balanced diagnostic subset; swaps are assumed label preserving; not proof of robustness to all attacks',
    }
    private_rows = []
    for name, transform in transformations.items():
        texts = [transform(text) for text in original_texts]
        predicted = [predictor.predict({'text': text})['prediction'] for text in texts]
        scores = predictor.model.decision_function([normalize_text(text) for text in texts])
        shifts = np.abs(scores - original_scores)
        changed = sum(a != b for a, b in zip(original, predicted))
        edited = sum(a != b for a, b in zip(original_texts, texts))
        result['variants'][name] = {
            'changed_predictions': changed, 'prediction_change_rate': changed / len(subset),
            'changed_input_texts': edited, 'metrics': classification_metrics(truth, predicted),
            'mean_absolute_decision_score_shift': float(shifts.mean()),
            'max_absolute_decision_score_shift': float(shifts.max()),
            'score_definition': 'LogisticRegression.decision_function margin for spam; not a calibrated probability',
        }
        for (_, row), text, before, after in zip(subset.iterrows(), texts, original, predicted):
            private_rows.append({'source_row': int(row['source_row']), 'variant': name,
                                 'text_before': row['text'], 'text_after': text, 'expected': row['target'],
                                 'prediction_before': before, 'prediction_after': after})
    atypical = '🛰️🧪🎮🌌' * 12
    response = predictor.predict({'text': atypical})
    nnz = int(predictor.model.named_steps['tfidf'].transform([normalize_text(atypical)]).nnz)
    result['atypical_input'] = {
        'description': 'Synthetic emoji-only text; syntactically valid but unlike ordinary English SMS',
        'characters': len(atypical), 'prediction': response['prediction'], 'nonzero_tfidf_features': nnz,
        'interpretation': 'Schema validation does not detect distribution shift; no formal OOD detector is implemented',
        'proposed_measure': 'Evaluate vocabulary coverage and abstention on a separate validation set before deploying',
    }
    write_json(root / 'data/processed/lab2/robustness-private.json', private_rows)
    write_json(root / 'metrics/robustness.json', result)
    return result
