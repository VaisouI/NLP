"""Метрики с фиксированным порядком классов; положительный класс — spam."""
from __future__ import annotations

import math

from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score


def classification_metrics(expected, predicted) -> dict:
    truth, labels = list(expected), list(predicted)
    if not truth or len(truth) != len(labels):
        raise ValueError('Expected equal, non-empty label sequences')
    if not set(truth + labels) <= {'ham', 'spam'}:
        raise ValueError('Only ham and spam labels are permitted')
    report = classification_report(truth, labels, labels=['ham', 'spam'], output_dict=True, zero_division=0)
    result = {
        'samples': len(truth),
        'accuracy': float(accuracy_score(truth, labels)),
        'balanced_accuracy': float(balanced_accuracy_score(truth, labels)),
        'f1_spam': float(f1_score(truth, labels, pos_label='spam', zero_division=0)),
        'macro_f1': float(f1_score(truth, labels, labels=['ham', 'spam'], average='macro', zero_division=0)),
        'per_class': {name: {key: float(value) for key, value in report[name].items()} for name in ['ham', 'spam']},
        'confusion_matrix': confusion_matrix(truth, labels, labels=['ham', 'spam']).tolist(),
        'label_order': ['ham', 'spam'],
    }
    if not all(math.isfinite(result[key]) for key in ['accuracy', 'balanced_accuracy', 'f1_spam', 'macro_f1']):
        raise ValueError('Non-finite metric is not permitted')
    return result
