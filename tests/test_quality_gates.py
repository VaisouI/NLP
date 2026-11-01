import copy
import hashlib
import json

import pytest

from src.quality_gates import GateError, data_gate, model_gate, security_gate, strict_json


@pytest.fixture
def control(tmp_path):
    rows = [{'source_row': 1, 'text': 'meet tomorrow', 'target': 'ham'},
            {'source_row': 2, 'text': 'free prize', 'target': 'spam'}]
    path = tmp_path / 'control.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    policy = {'max_file_bytes': 10000, 'fields': ['source_row', 'text', 'target'],
              'input_limits': {'max_characters': 4096, 'max_utf8_bytes': 16384},
              'min_samples': 2, 'max_samples': 2, 'class_fraction': {'ham': [.4, .6], 'spam': [.4, .6]},
              'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'dataset_version': 'd1',
              'split_version': 's1', 'split_sha256': 'a' * 64, 'fixture_version': 'f1'}
    metadata = {key: policy[key] for key in ('dataset_version', 'split_version', 'split_sha256',
                                           'fixture_version', 'sha256')}
    return path, rows, metadata, policy


def test_valid_control_reports_exact_counts(control):
    path, _, metadata, policy = control
    result = data_gate(path, metadata, policy)
    assert result['passed'] is True
    assert result['classes'] == {'ham': 1, 'spam': 1}
    assert result['samples'] == 2


@pytest.mark.parametrize(('change', 'error'), [
    ('schema', 'schema'), ('label', 'class label'), ('missing', 'Invalid text'),
    ('type', 'Invalid text'), ('nan', 'Non-finite'), ('duplicate', 'Duplicate'),
    ('imbalance', 'distribution'), ('few', 'sample count'), ('bytes', 'SHA256'),
])
def test_corrupted_copy_is_rejected_without_changing_original(control, change, error):
    original, rows, metadata, policy = control
    before = original.read_bytes()
    path = original.with_name('corrupted-copy.jsonl')
    if change == 'schema':
        rows[0]['message'] = rows[0].pop('text')
    elif change == 'label':
        rows[0]['target'] = 'unknown'
    elif change == 'missing':
        rows[0]['text'] = None
    elif change == 'type':
        rows[0]['text'] = ['wrong shape']
    elif change == 'nan':
        rows[0]['source_row'] = float('nan')
    elif change == 'duplicate':
        rows[1]['text'] = '  MEET tomorrow '
    elif change == 'imbalance':
        rows[1]['target'] = 'ham'
    elif change == 'few':
        rows.pop()
    elif change == 'bytes':
        rows[0]['text'] = 'another valid text'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(GateError, match=error):
        data_gate(path, metadata, policy)
    assert original.read_bytes() == before


def test_data_version_mismatch_fails(control):
    path, _, metadata, policy = control
    metadata['dataset_version'] = 'different'
    with pytest.raises(GateError, match='metadata'):
        data_gate(path, metadata, policy)


@pytest.mark.parametrize('payload', ['{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}'])
def test_ambiguous_or_nonfinite_json_is_rejected(payload):
    with pytest.raises(GateError):
        strict_json(payload)


@pytest.fixture
def quality():
    policy = {'dataset_version': 'd1', 'split_version': 's1', 'split_sha256': 'a' * 64,
              'main_metric': 'f1_spam', 'metric_definition': 'binary F1 spam',
              'role': 'fixed_ci_control', 'samples': 100, 'max_relative_degradation': .05}
    baseline = {key: value for key, value in policy.items() if key != 'max_relative_degradation'}
    baseline.update(value=.8, model_sha256='b' * 64)
    return baseline, copy.deepcopy(baseline), policy


@pytest.mark.parametrize(('value', 'passes'), [(.76, True), (.759, False), (.9, True), (0, False)])
def test_relative_threshold_including_exact_boundary(quality, value, passes):
    baseline, candidate, policy = quality
    candidate['value'] = value
    result = model_gate(candidate, baseline, policy)
    assert result['passed'] is passes
    assert result['threshold'] == pytest.approx(.76)
    assert baseline['value'] == .8


@pytest.mark.parametrize('value', [None, '0.9', True, float('nan'), float('inf'), -.1, 1.1])
def test_invalid_metric_fails_closed(quality, value):
    baseline, candidate, policy = quality
    candidate['value'] = value
    with pytest.raises(GateError, match='metric'):
        model_gate(candidate, baseline, policy)


def test_missing_metric_and_incompatible_data_fail(quality):
    baseline, candidate, policy = quality
    del candidate['value']
    with pytest.raises(GateError, match='metric'):
        model_gate(candidate, baseline, policy)
    candidate['value'] = .9
    candidate['split_sha256'] = 'c' * 64
    with pytest.raises(GateError, match='split_sha256'):
        model_gate(candidate, baseline, policy)


def test_zero_baseline_requires_reviewed_absolute_policy(quality):
    baseline, candidate, policy = quality
    baseline['value'] = 0
    with pytest.raises(GateError, match='Zero baseline'):
        model_gate(candidate, baseline, policy)


@pytest.fixture
def scan():
    report = {'SchemaVersion': 2, 'CreatedAt': '2026-11-01T00:00:00Z',
              'ArtifactName': 'own-test-image', 'ArtifactType': 'container_image',
              'Results': [{'Class': 'os-pkgs', 'Target': 'Debian', 'Type': 'debian'}]}
    return report, {'blocked_severities': ['CRITICAL', 'UNKNOWN']}


def test_real_scan_with_no_vulnerabilities_passes(scan):
    report, policy = scan
    assert security_gate(report, policy)['passed'] is True


@pytest.mark.parametrize(('severity', 'passes'), [('CRITICAL', False), ('UNKNOWN', False),
                                                ('HIGH', True), ('MEDIUM', True), ('LOW', True)])
def test_security_policy_blocks_critical_and_unknown(scan, severity, passes):
    report, policy = scan
    report['Results'][0]['Vulnerabilities'] = [
        {'VulnerabilityID': 'SIMULATED-001', 'PkgName': 'test-only', 'Severity': severity}]
    assert security_gate(report, policy)['passed'] is passes


def test_missing_severity_is_not_treated_as_safe(scan):
    report, policy = scan
    report['Results'][0]['Vulnerabilities'] = [{'VulnerabilityID': 'SIMULATED-001', 'PkgName': 'test-only'}]
    assert security_gate(report, policy)['passed'] is False


@pytest.mark.parametrize('field', ['SchemaVersion', 'CreatedAt', 'ArtifactName', 'Results'])
def test_incomplete_scan_is_not_a_clean_scan(scan, field):
    report, policy = scan
    del report[field]
    with pytest.raises(GateError):
        security_gate(report, policy)


@pytest.fixture
def reviewed(scan):
    report, policy = scan
    report['Results'][0]['Vulnerabilities'] = [
        {'VulnerabilityID': 'CVE-TEST-1', 'PkgName': 'test-package',
         'InstalledVersion': '1.0', 'Severity': 'UNKNOWN'}]
    source = {'cveMetadata': {'cveId': 'CVE-TEST-1', 'state': 'PUBLISHED'},
              'containers': {'adp': [{'providerMetadata': {'shortName': 'CISA-ADP'},
                                      'metrics': [{'cvssV3_1': {'version': '3.1', 'baseScore': 7.5,
                                                               'baseSeverity': 'HIGH'}}]}]}}
    evidence = {'CVE-TEST-1': {'document': source, 'source': 'https://example.test/primary-cve',
                              'sha256': 'a' * 64, 'source_commit': 'b' * 40}}
    return report, policy, evidence


def test_primary_severity_is_reported_without_hiding_scanner_finding(reviewed):
    result = security_gate(*reviewed)
    assert result['passed'] is True
    assert result['findings'] == 1
    assert result['resolved_unknown'][0]['scanner_severity'] == 'UNKNOWN'
    assert result['resolved_unknown'][0]['resolved_severity'] == 'HIGH'


def test_primary_critical_still_blocks(reviewed):
    report, policy, evidence = reviewed
    evidence['CVE-TEST-1']['document']['containers']['adp'][0]['metrics'][0]['cvssV3_1'] = {
        'version': '3.1', 'baseScore': 9.8, 'baseSeverity': 'CRITICAL'}
    assert security_gate(report, policy, evidence)['passed'] is False


def test_scanner_critical_cannot_be_downgraded_by_review(reviewed):
    report, policy, evidence = reviewed
    report['Results'][0]['Vulnerabilities'][0]['Severity'] = 'CRITICAL'
    assert security_gate(report, policy, evidence)['passed'] is False


def test_primary_evidence_does_not_cover_another_cve(reviewed):
    report, policy, evidence = reviewed
    report['Results'][0]['Vulnerabilities'][0]['VulnerabilityID'] = 'CVE-TEST-2'
    assert security_gate(report, policy, evidence)['passed'] is False


def test_missing_or_mismatched_primary_evidence_fails_closed(reviewed):
    report, policy, evidence = reviewed
    assert security_gate(report, policy, {})['passed'] is False
    evidence['CVE-TEST-1']['document']['cveMetadata']['cveId'] = 'different'
    with pytest.raises(GateError, match='another CVE'):
        security_gate(report, policy, evidence)


def test_missing_cvss_does_not_make_unknown_safe(reviewed):
    report, policy, evidence = reviewed
    evidence['CVE-TEST-1']['document']['containers']['adp'][0]['metrics'] = []
    assert security_gate(report, policy, evidence)['passed'] is False


def test_highest_primary_severity_is_used_across_cvss_versions(reviewed):
    report, policy, evidence = reviewed
    evidence['CVE-TEST-1']['document']['containers']['cna'] = {
        'metrics': [{'cvssV4_0': {'version': '4.0', 'baseScore': 9.3, 'baseSeverity': 'CRITICAL'}}]}
    result = security_gate(report, policy, evidence)
    assert result['passed'] is False
    assert result['resolved_unknown'][0]['resolved_severity'] == 'CRITICAL'
