"""Обучение и оценка без ручных ячеек; baseline не заменяется кандидатом."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED

import sklearn
import skops.io as sio
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from src.artifacts import MODEL_RELATIVE, REFERENCE_RELATIVE, load_verified_model, preferred_reference
from src.ml_metrics import classification_metrics
from src.prediction import SmsPredictor
from src.preprocessing import NORMALIZATION_VERSION, configured_policy, read_config
from src.splitting import canonical_json, prepare_splits


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def frozen_json(path: Path, value: object) -> None:
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise ValueError(f'Existing baseline differs: {path.name}; use a new reviewed model/data version')
    else:
        write_json(path, value)


def training_fingerprint(root: Path) -> str:
    config = read_config(root)
    files = ['src/preprocessing.py', 'src/splitting.py', 'src/training.py', 'src/dataset.py']
    return hashlib.sha256(canonical_json({
        'configuration': config,
        'source_sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files},
    })).hexdigest()


def build_pipeline(config: dict) -> Pipeline:
    vectorizer = dict(config['tfidf'])
    vectorizer['ngram_range'] = tuple(vectorizer['ngram_range'])
    return Pipeline([
        ('tfidf', TfidfVectorizer(lowercase=False, **vectorizer)),
        ('classifier', LogisticRegression(random_state=config['seed'], **config['logistic_regression'])),
    ])


def run_training(root: Path) -> dict:
    frame, indices, dataset = prepare_splits(root)
    config = read_config(root)
    fingerprint = training_fingerprint(root)
    path = root / MODEL_RELATIVE
    reference = root / REFERENCE_RELATIVE
    cached = path.exists()
    if cached:
        model, manifest = load_verified_model(path, preferred_reference(root))
        if manifest.get('training_fingerprint') != fingerprint or manifest.get('split_sha256') != dataset['split_sha256']:
            raise ValueError('Existing model was trained with different code, configuration or data; baseline is preserved')
    else:
        if reference.exists():
            raise ValueError('A model reference exists but its private artifact is missing; restore the artifact before continuing')
        train = frame.iloc[indices['train']]
        model = build_pipeline(config)
        started = time.perf_counter()
        model.fit(train['normalized'].tolist(), train['target'].tolist())
        seconds = time.perf_counter() - started
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        temporary = path.with_name(path.name + '.tmp')
        sio.dump(model, temporary, compression=ZIP_DEFLATED, compresslevel=6)
        temporary.chmod(0o600)
        temporary.replace(path)
        data = path.read_bytes()
        manifest = {
            'model_version': config['model_version'], 'format': 'skops',
            'file': MODEL_RELATIVE.as_posix(), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'sklearn_version': sklearn.__version__, 'normalization_version': NORMALIZATION_VERSION,
            'dataset_version': dataset['dataset_version'], 'split_sha256': dataset['split_sha256'],
            'training_fingerprint': fingerprint, 'config_sha256': hashlib.sha256(canonical_json(config)).hexdigest(),
            'trained_at_utc': datetime.now(timezone.utc).isoformat(),
            'training_seconds': seconds, 'python_version': platform.python_version(),
            'source_commit': os.environ.get('ML_LAB2_SOURCE_COMMIT', 'local-preparation'),
        }
        frozen_json(reference, manifest)
        # Проверяем сохранённый файл, а не только объект в памяти.
        model, loaded = load_verified_model(path, reference)
        if loaded != manifest:
            raise ValueError('Saved model reference differs after loading')
    predictor = SmsPredictor(model, config['model_version'], configured_policy(root))
    metrics = {}
    errors = []
    private_errors = []
    for name in ['ci', 'test']:
        subset = frame.iloc[indices[name]]
        predicted = [predictor.predict({'text': text})['prediction'] for text in subset['text']]
        metrics[name] = classification_metrics(subset['target'].tolist(), predicted)
        if name == 'test':
            vocabulary = model.named_steps['tfidf']
            for (_, row), result in zip(subset.iterrows(), predicted):
                if result != row['target']:
                    vector = vocabulary.transform([row['normalized']])
                    features = int(vector.nnz)
                    score = float(model.decision_function([row['normalized']])[0])
                    errors.append({
                        'source_row': int(row['source_row']), 'expected': row['target'], 'predicted': result,
                        'characters': len(row['text']), 'known_nonzero_features': features, 'decision_score_spam': score,
                        'interpretation': 'Лексических признаков недостаточно для правильного решения; анализ по длине и числу признаков не устанавливает причину ошибки',
                    })
                    names = vocabulary.get_feature_names_out()
                    weights = model.named_steps['classifier'].coef_[0]
                    contributions = sorted(({'term': str(names[index]), 'contribution': float(value * weights[index])}
                                            for index, value in zip(vector.indices, vector.data)),
                                           key=lambda item: abs(item['contribution']), reverse=True)[:5]
                    private_errors.append({'source_row': int(row['source_row']), 'text': row['text'],
                                           'expected': row['target'], 'predicted': result, 'decision_score_spam': score,
                                           'top_linear_contributions': contributions,
                                           'interpretation': 'Signed TF-IDF times LR coefficient explains the model score, not real-world intent'})
    dummy = DummyClassifier(strategy='most_frequent')
    dummy.fit(frame.iloc[indices['train']]['normalized'].tolist(), frame.iloc[indices['train']]['target'].tolist())
    test = frame.iloc[indices['test']]
    dummy_metrics = classification_metrics(test['target'], dummy.predict(test['normalized'].tolist()))
    common = {
        'model_version': config['model_version'], 'model_sha256': manifest['sha256'],
        'main_metric': 'f1_spam', 'dataset_version': dataset['dataset_version'],
        'dataset_sha256': dataset['source_sha256'], 'split_version': dataset['split_version'],
        'split_sha256': dataset['split_sha256'], 'seed': config['seed'],
        'metric_definition': 'binary F1; positive label spam; zero_division=0',
    }
    for name, file in [('test', 'baseline.json'), ('ci', 'baseline_ci.json')]:
        frozen_json(root / 'metrics' / file, {
            **common, 'role': 'final_test' if name == 'test' else 'fixed_ci_control',
            'value': metrics[name]['f1_spam'], 'samples': metrics[name]['samples'], 'metrics': metrics[name],
        })
    parameters = {
        'configuration': config, 'training_fingerprint': fingerprint,
        'model_sha256': manifest['sha256'], 'training_seconds': manifest['training_seconds'],
        'trained_at_utc': manifest['trained_at_utc'], 'sklearn_version': sklearn.__version__,
        'features_learned': len(model.named_steps['tfidf'].vocabulary_),
        'fit_scope': 'train only; no hyperparameter search; CI and final test excluded from fit',
    }
    write_json(root / 'metrics/training.json', parameters)
    write_json(root / 'metrics/lab2-data.json', dataset)
    write_json(root / 'metrics/majority-baseline.json', dummy_metrics)
    write_json(root / 'metrics/error-analysis.json', {'total_errors': len(errors), 'examples': errors[:8], 'raw_text_published': False})
    write_json(root / 'data/processed/lab2/error-analysis-private.json', private_errors[:8])
    return {'dataset': dataset, 'manifest': manifest, 'parameters': parameters, 'metrics': metrics,
            'dummy': dummy_metrics, 'errors': errors[:8], 'reused_existing_model': cached}
