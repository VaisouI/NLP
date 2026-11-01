"""Fail-closed policies for fixed CI data, model quality and Trivy reports."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from src.preprocessing import InputPolicy, InputValidationError, normalize_text, validate_payload


class GateError(ValueError):
    """An input or policy does not meet the documented CI contract."""


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise GateError('Duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise GateError('Non-finite JSON constant: ' + value)


def strict_json(raw: str | bytes) -> object:
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def read_json(path: Path) -> dict:
    value = strict_json(path.read_bytes())
    if type(value) is not dict:
        raise GateError('Expected a JSON object')
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def data_gate(path: Path, metadata: dict, policy: dict) -> dict:
    input_policy = InputPolicy(**policy['input_limits'])
    if path.stat().st_size > policy['max_file_bytes']:
        raise GateError('CI data file exceeds size limit')
    for name in ('dataset_version', 'split_version', 'split_sha256', 'fixture_version'):
        if metadata.get(name) != policy[name]:
            raise GateError('Incompatible data metadata: ' + name)
    counts = Counter()
    identifiers = set()
    normalized = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        row = strict_json(line)
        if type(row) is not dict or set(row) != set(policy['fields']):
            raise GateError('Invalid data schema: required source_row, text, target')
        if type(row['source_row']) is not int or row['source_row'] < 0:
            raise GateError('Invalid source_row type or range')
        if type(row['target']) is not str or row['target'] not in policy['class_fraction']:
            raise GateError('Invalid class label')
        try:
            validate_payload({'text': row['text']}, input_policy)
        except InputValidationError as exc:
            raise GateError('Invalid text input: ' + exc.code) from exc
        key = normalize_text(row['text'])
        if row['source_row'] in identifiers or key in normalized:
            raise GateError('Duplicate source ID or normalized text')
        identifiers.add(row['source_row'])
        normalized.add(key)
        counts[row['target']] += 1
    samples = sum(counts.values())
    if not policy['min_samples'] <= samples <= policy['max_samples']:
        raise GateError('CI sample count is outside policy')
    for label, bounds in policy['class_fraction'].items():
        fraction = counts[label] / samples
        if not bounds[0] <= fraction <= bounds[1]:
            raise GateError('CI class distribution is outside policy: ' + label)
    sha = digest(path)
    if sha != policy['sha256'] or metadata.get('sha256') != sha:
        raise GateError('CI data SHA256 mismatch')
    return {'passed': True, 'samples': samples, 'classes': dict(counts), 'sha256': sha,
            'fixture_version': policy['fixture_version']}


def _finite_metric(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise GateError('Invalid finite F1 metric: ' + name)
    return float(value)


def model_gate(candidate: dict, baseline: dict, policy: dict) -> dict:
    for record, name in ((baseline, 'baseline'), (candidate, 'candidate')):
        for field in ('dataset_version', 'split_version', 'split_sha256', 'main_metric',
                      'metric_definition', 'role', 'samples'):
            if record.get(field) != policy[field]:
                raise GateError('Incompatible ' + name + ': ' + field)
        if not re.fullmatch(r'[0-9a-f]{64}', str(record.get('model_sha256', ''))):
            raise GateError('Missing or invalid model SHA256')
        if type(record.get('samples')) is not int:
            raise GateError('Invalid sample count type')
    reference = _finite_metric(baseline.get('value'), 'baseline')
    value = _finite_metric(candidate.get('value'), 'candidate')
    if reference <= 0:
        raise GateError('Zero baseline requires a separately reviewed absolute policy')
    degradation = policy['max_relative_degradation']
    if type(degradation) not in (int, float) or not math.isfinite(degradation) or not 0 <= degradation < 1:
        raise GateError('Invalid degradation policy')
    threshold = reference * (1 - degradation)
    return {'passed': value >= threshold, 'baseline': reference, 'candidate': value,
            'threshold': threshold, 'relation': 'candidate >= baseline * 0.95',
            'relative_change': (value - reference) / reference,
            'model_sha256': candidate['model_sha256'], 'split_sha256': candidate['split_sha256']}


def _primary_severity(item: dict, evidence: dict) -> tuple[str, dict | None]:
    original = item.get('Severity', 'UNKNOWN')
    if original != 'UNKNOWN':
        return original, None
    record = evidence.get(item['VulnerabilityID'])
    if record is None:
        return original, None
    source = record['document']
    if source.get('cveMetadata', {}).get('cveId') != item['VulnerabilityID']:
        raise GateError('Primary evidence refers to another CVE')
    if source['cveMetadata'].get('state') != 'PUBLISHED':
        raise GateError('CVE evidence must be published')
    containers = source.get('containers', {})
    providers = [containers.get('cna', {})] + [provider for provider in containers.get('adp', [])
                                             if provider.get('providerMetadata', {}).get('shortName') == 'CISA-ADP']
    scores = []
    ranks = {'NONE': 0, 'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'CRITICAL': 4}
    for provider in providers:
        for metric in provider.get('metrics', []):
            for key, version in (('cvssV3_0', '3.0'), ('cvssV3_1', '3.1'), ('cvssV4_0', '4.0')):
                cvss = metric.get(key)
                if cvss is None:
                    continue
                score = cvss.get('baseScore')
                if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 10:
                    raise GateError('Invalid primary CVSS evidence')
                severity = ('CRITICAL' if score >= 9 else 'HIGH' if score >= 7 else 'MEDIUM' if score >= 4
                            else 'LOW' if score > 0 else 'NONE')
                if cvss.get('baseSeverity') != severity or cvss.get('version') != version:
                    raise GateError('CVSS score and severity disagree')
                scores.append((ranks[severity], score, severity, version))
    if not scores:
        return original, None
    _, score, severity, version = max(scores)
    return severity, {'VulnerabilityID': item['VulnerabilityID'], 'PkgName': item['PkgName'],
                      'InstalledVersion': item.get('InstalledVersion'), 'scanner_severity': original,
                      'resolved_severity': severity, 'cvss_version': version, 'cvss_score': score,
                      'source': record['source'], 'evidence_sha256': record['sha256'],
                      'source_commit': record['source_commit']}


def security_gate(report: dict, policy: dict, evidence: dict | None = None) -> dict:
    if report.get('SchemaVersion') != 2 or report.get('ArtifactType') != 'container_image':
        raise GateError('Unsupported or incomplete Trivy image report')
    if not report.get('ArtifactName') or not report.get('CreatedAt'):
        raise GateError('Missing scan identity or timestamp')
    results = report.get('Results')
    if type(results) is not list or not results:
        raise GateError('Missing scan results; scan failure is not a clean result')
    if not any(type(item) is dict and item.get('Class') == 'os-pkgs' for item in results):
        raise GateError('Operating-system package scan is missing')
    blocked = []
    resolved = []
    findings = 0
    for result in results:
        if type(result) is not dict or result.get('Class') not in {'os-pkgs', 'lang-pkgs'}:
            raise GateError('Invalid vulnerability scan result')
        vulnerabilities = result.get('Vulnerabilities')
        if vulnerabilities is None:
            vulnerabilities = []
        if type(vulnerabilities) is not list:
            raise GateError('Malformed vulnerability list')
        for item in vulnerabilities:
            if type(item) is not dict or not item.get('VulnerabilityID') or not item.get('PkgName'):
                raise GateError('Malformed vulnerability finding')
            severity, resolution = _primary_severity(item, evidence or {})
            if resolution is not None:
                resolved.append(resolution)
            findings += 1
            if severity not in {'NONE', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL', 'UNKNOWN'}:
                raise GateError('Invalid vulnerability severity')
            if severity in policy['blocked_severities']:
                blocked.append({key: item.get(key) for key in
                                ('VulnerabilityID', 'PkgName', 'InstalledVersion', 'FixedVersion', 'Severity')})
    return {'passed': not blocked, 'findings': findings, 'blocked': blocked,
            'policy': policy['blocked_severities'], 'resolved_unknown': resolved,
            'scan_created_at': report['CreatedAt']}
