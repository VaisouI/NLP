#!/usr/bin/env python3
"""Ordered LR3 commands; every failing gate returns a nonzero process status."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.quality_gates import GateError, data_gate, digest, model_gate, read_json, security_gate

REPORTS = ROOT / 'reports/lab3'
ARTIFACTS = ROOT / 'artifacts/ci'


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def scenario() -> str:
    name = read_json(ROOT / 'config/ci_scenario.json').get('scenario')
    if name not in {'normal', 'bad-data', 'weak-model', 'security-policy'}:
        raise GateError('Unknown CI scenario')
    return name


def fixture_path() -> Path:
    return ARTIFACTS / ('invalid-ci-copy.jsonl' if scenario() == 'bad-data' else 'control.jsonl')


def check_data() -> dict:
    return data_gate(fixture_path(), read_json(ARTIFACTS / 'control-manifest.json'),
                     read_json(ROOT / 'config/data_gate.json'))


def prepare() -> dict:
    from src.splitting import canonical_json, prepare_splits

    REPORTS.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, 'scripts/download_dataset.py'], cwd=ROOT, check=True, timeout=120)
    frame, indices, summary = prepare_splits(ROOT)
    rows = [{'source_row': int(row.source_row), 'text': row.text, 'target': row.target}
            for row in frame.iloc[indices['ci']].itertuples()]
    control = ARTIFACTS / 'control.jsonl'
    control.write_bytes(b''.join(canonical_json(row) + b'\n' for row in rows))
    metadata = {key: summary[key] for key in ('dataset_version', 'split_version', 'split_sha256')}
    metadata.update(fixture_version='lab3-ci-jsonl-v1', sha256=digest(control), samples=len(rows))
    write(ARTIFACTS / 'control-manifest.json', metadata)
    if scenario() == 'bad-data':
        damaged = [dict(row) for row in rows]
        damaged[0]['message'] = damaged[0].pop('text')
        (ARTIFACTS / 'invalid-ci-copy.jsonl').write_bytes(b''.join(canonical_json(row) + b'\n' for row in damaged))
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True,
                            check=True, timeout=10).stdout.strip()
    result = {**metadata, 'commit': commit, 'scenario': scenario(),
              'python': platform.python_version(), 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'workflow_run_id': os.environ.get('GITHUB_RUN_ID'),
              'source_files_sha256': {name: digest(ROOT / name) for name in
                                      ('src/training.py', 'src/preprocessing.py', 'src/splitting.py',
                                       'config/lab2.json', 'metrics/baseline_ci.json')},
              'train_samples': len(indices['train']), 'final_test_evaluated': False}
    write(REPORTS / 'provenance.json', result)
    return result


def train() -> dict:
    import sklearn
    import skops.io as sio
    from src.artifacts import load_verified_model
    from src.preprocessing import NORMALIZATION_VERSION, read_config
    from src.splitting import canonical_json, prepare_splits
    from src.training import build_pipeline

    check_data()
    frame, indices, summary = prepare_splits(ROOT)
    policy = read_json(ROOT / 'config/data_gate.json')
    if summary['split_sha256'] != policy['split_sha256']:
        raise GateError('Training split differs from the LR2 reference')
    config = read_config(ROOT)
    subset = frame.iloc[indices['train']]
    model = build_pipeline(config)
    model.fit(subset['normalized'].tolist(), subset['target'].tolist())
    kind = 'lab2_tfidf_logistic_regression'
    if scenario() == 'weak-model':
        # An actual saved predictor with constant ham output, evaluated on the real control data.
        model.named_steps['classifier'].coef_[:] = 0
        model.named_steps['classifier'].intercept_[:] = -100
        kind = 'constant_ham_demo'
    destination = ARTIFACTS / 'model.skops'
    sio.dump(model, destination, compression=ZIP_DEFLATED, compresslevel=6)
    manifest = {
        'format': 'skops', 'model_version': config['model_version'],
        'sha256': digest(destination), 'bytes': destination.stat().st_size,
        'normalization_version': NORMALIZATION_VERSION, 'sklearn_version': sklearn.__version__,
        'config_sha256': hashlib.sha256(canonical_json(config)).hexdigest(),
        'dataset_version': summary['dataset_version'], 'split_sha256': summary['split_sha256'],
        'artifact_role': 'ephemeral_ci_candidate', 'candidate_kind': kind,
        'origin_lab2_model_sha256': read_json(ROOT / 'security/model-manifest-lab2-v1.json')['sha256'],
        'fit_scope': 'train only; fixed CI and final test excluded from fit',
        'trained_at_utc': datetime.now(timezone.utc).isoformat(),
    }
    write(ARTIFACTS / 'model-manifest.json', manifest)
    load_verified_model(destination, ARTIFACTS / 'model-manifest.json')
    write(REPORTS / 'candidate-manifest.json', manifest)
    (REPORTS / 'model.SHA256SUMS').write_text(manifest['sha256'] + '  artifacts/ci/model.skops\n')
    return manifest


def evaluate() -> dict:
    from src.artifacts import load_verified_model
    from src.ml_metrics import classification_metrics
    from src.prediction import SmsPredictor
    from src.quality_gates import strict_json

    check_data()
    model, manifest = load_verified_model(ARTIFACTS / 'model.skops', ARTIFACTS / 'model-manifest.json')
    rows = [strict_json(line) for line in (ARTIFACTS / 'control.jsonl').read_text().splitlines()]
    predictor = SmsPredictor(model)
    metrics = classification_metrics([row['target'] for row in rows],
                                     [predictor.predict({'text': row['text']})['prediction'] for row in rows])
    policy = read_json(ROOT / 'config/model_gate.json')
    baseline_path = ROOT / 'metrics/baseline_ci.json'
    if digest(baseline_path) != policy['baseline_file_sha256']:
        raise GateError('Frozen LR2 baseline file SHA256 differs from policy')
    candidate = {key: policy[key] for key in ('dataset_version', 'split_version', 'split_sha256',
                                             'main_metric', 'metric_definition', 'role', 'samples')}
    candidate.update(value=metrics['f1_spam'], metrics=metrics, model_sha256=manifest['sha256'],
                     model_version=manifest['model_version'], candidate_kind=manifest['candidate_kind'])
    write(REPORTS / 'candidate-metrics.json', candidate)
    result = model_gate(candidate, read_json(baseline_path), policy)
    write(REPORTS / 'model-comparison.json', result)
    return result


def audit() -> dict:
    command = [sys.executable, '-m', 'pip_audit', '-r', 'requirements.txt', '--disable-pip', '--no-deps',
               '--strict', '--format=json', '--output', str(REPORTS / 'pip-audit.json')]
    completed = subprocess.run(command, cwd=ROOT, check=False, timeout=300)
    if completed.returncode:
        raise GateError('pip-audit returned failure: ' + str(completed.returncode))
    report = read_json(REPORTS / 'pip-audit.json')
    dependencies = report.get('dependencies')
    if type(dependencies) is not list or not dependencies:
        raise GateError('Dependency audit did not produce a complete report')
    for dependency in dependencies:
        if dependency.get('skip_reason') or type(dependency.get('vulns')) is not list or dependency['vulns']:
            raise GateError('Dependency audit has findings or skipped packages')
    return {'passed': True, 'dependencies': len(dependencies), 'vulnerabilities': 0, 'skipped': 0,
            'policy': 'block every finding; operational failure and incomplete audit fail closed'}


def scan() -> dict:
    trivy = shutil.which('trivy')
    if trivy is None:
        raise GateError('Trivy executable is missing')
    version = subprocess.run([trivy, '--version'], check=True, capture_output=True, text=True, timeout=15).stdout
    (REPORTS / 'trivy-version.txt').write_text(version)
    # Exit 0 collects findings for our stricter policy; operational scanner failures still raise.
    subprocess.run([trivy, 'config', '--exit-code', '1', '--format', 'json', '--output',
                    str(REPORTS / 'trivy-config.json'), 'Dockerfile'], cwd=ROOT, check=True, timeout=180)
    subprocess.run([trivy, 'image', '--scanners', 'vuln', '--exit-code', '0', '--format', 'json',
                    '--output', str(REPORTS / 'trivy-image.json'), 'ml-project:lab3'],
                   cwd=ROOT, check=True, timeout=480)
    result = security_gate(read_json(REPORTS / 'trivy-image.json'), read_json(ROOT / 'config/security_gate.json'))
    write(REPORTS / 'real-image-security-policy.json', result)
    if not result['passed']:
        return result
    if scenario() == 'security-policy':
        result = security_gate(read_json(ROOT / 'tests/fixtures/simulated-critical-trivy.json'),
                               read_json(ROOT / 'config/security_gate.json'))
        result['demonstration'] = 'SIMULATION of policy input; real scanner output is kept separately'
    return result


def smoke() -> dict:
    uid = subprocess.run(['docker', 'run', '--rm', '--entrypoint', 'id', 'ml-project:lab3', '-u'],
                         check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    if not uid.isdecimal() or int(uid) == 0:
        raise GateError('Runtime container must have a nonzero UID')
    completed = subprocess.run(['docker', 'run', '--rm', '--network=none', '--read-only',
                                '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64',
                                '--memory=512m', '--cpus=1', 'ml-project:lab3', '--self-test'],
                               check=True, capture_output=True, text=True, timeout=60)
    result = json.loads(completed.stdout)
    if result.get('passed') is not True:
        raise GateError('Container smoke test did not pass')
    return {'passed': True, 'uid': int(uid), 'smoke': result}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'data', 'train', 'model', 'audit', 'scan', 'smoke'])
    args = parser.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    functions = {'prepare': prepare, 'data': check_data, 'train': train, 'model': evaluate,
                 'audit': audit, 'scan': scan, 'smoke': smoke}
    try:
        result = functions[args.stage]()
        code = 0 if result.get('passed', True) is True else 1
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result = {'passed': False, 'error_type': type(exc).__name__, 'error': str(exc)}
        code = 1
    result.update(exit_code=code, stage=args.stage, checked_at_utc=datetime.now(timezone.utc).isoformat())
    write(REPORTS / (args.stage + '-status.json'), result)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
