#!/usr/bin/env python3
"""Настоящие HTTP-проверки, ограниченный сценарий и снимки страницы."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from prometheus_client.parser import text_string_to_metric_families

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=90, **kwargs).stdout.strip()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_health(url: str, expected: int = 200):
    with httpx.Client(trust_env=False, timeout=2) as client:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                response = client.get(url + '/health')
                if response.status_code == expected:
                    return response
            except httpx.HTTPError:
                pass
            time.sleep(.1)
    raise RuntimeError('Service did not reach the expected readiness state')


def metric(text, name, labels):
    return sum(sample.value for family in text_string_to_metric_families(text) for sample in family.samples
               if sample.name == name and sample.labels == labels)


def exercise(url: str, token: str, metrics_token: str, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    authorized = {'Authorization': 'Bearer ' + token}
    monitoring = {'Authorization': 'Bearer ' + metrics_token}
    cases = []
    with httpx.Client(base_url=url, trust_env=False, timeout=10) as client:
        def check(name, expected, response):
            record = {'case': name, 'expected': expected, 'actual': response.status_code, 'passed': response.status_code == expected}
            if response.headers.get('content-type', '').startswith('application/json'):
                record['response'] = response.json()
            cases.append(record)
            if not record['passed']:
                write(destination / 'http-cases.json', cases)
                raise RuntimeError('Unexpected HTTP result in ' + name)
            return response

        check('healthy', 200, client.get('/health'))
        check('page', 200, client.get('/'))
        check('valid_prediction', 200, client.post('/predict', headers=authorized, json={'text': 'Are we meeting for lunch tomorrow?'}))
        before_invalid = client.get('/metrics', headers=monitoring).text
        check('missing_token', 401, client.post('/predict', json={'text': 'Hello'}))
        check('wrong_token', 401, client.post('/predict', headers={'Authorization': 'Bearer invalid'}, json={'text': 'Hello'}))
        check('empty_input', 422, client.post('/predict', headers=authorized, json={'text': '  '}))
        check('wrong_type', 422, client.post('/predict', headers=authorized, json={'text': 7}))
        check('decoded_text_limit', 413, client.post('/predict', headers=authorized, json={'text': 'a' * 4097}))
        check('unsupported_media', 415, client.post('/predict', headers={**authorized, 'Content-Type': 'text/plain'}, content='hello'))
        check('invalid_json', 400, client.post('/predict', headers={**authorized, 'Content-Type': 'application/json'}, content='{'))
        check('stream_without_content_length', 413, client.post('/predict', headers={**authorized, 'Content-Type': 'application/json'},
              content=iter([b'x' * 8192] * 5)))
        check('metrics_requires_credential', 401, client.get('/metrics'))
        after_invalid = client.get('/metrics', headers=monitoring).text
        if metric(before_invalid, 'ml_api_inference_total', {}) != metric(after_invalid, 'ml_api_inference_total', {}):
            raise RuntimeError('A rejected HTTP input reached inference')
        # A separate interval for a bounded detection demonstration, not mixed with the negative tests.
        (destination / 'metrics-before.txt').write_text(after_invalid)
        start = datetime.now(timezone.utc).isoformat()
        statuses = [client.post('/predict', headers={'Authorization': 'Bearer invalid-demo'}, json={'text': 'demo'}).status_code for _ in range(3)]
        end = datetime.now(timezone.utc).isoformat()
        after = client.get('/metrics', headers=monitoring).text
        (destination / 'metrics-after.txt').write_text(after)
        delta = metric(after, 'ml_api_requests_total', {'route': '/predict', 'status': '401'}) - metric(after_invalid, 'ml_api_requests_total', {'route': '/predict', 'status': '401'})
        if statuses != [401] * 3 or delta != 3:
            raise RuntimeError('Controlled authentication scenario did not match metrics')
        # The server in this demonstration has a documented short 2-second rate window.
        time.sleep(2.1)
        rate = [client.post('/predict', headers=authorized, json={'text': 'Meeting at noon'}).status_code for _ in range(11)]
        if rate != [200] * 10 + [429]:
            raise RuntimeError('Rate limit did not enforce ten requests per demonstration window')
        time.sleep(2.1)
        recovery = check('valid_after_scenario', 200, client.post('/predict', headers=authorized, json={'text': 'Meeting at noon'}))
        check('healthy_after_scenario', 200, client.get('/health'))
    write(destination / 'http-cases.json', cases)
    result = {'passed': True, 'start_utc': start, 'end_utc': end, 'statuses': statuses,
              'http_401_delta': delta, 'rate_statuses': rate, 'recovered_http_status': recovery.status_code,
              'demo_rate_policy': {'requests': 10, 'period_seconds': 2},
              'default_rate_policy': {'requests': 10, 'period_seconds': 60},
              'rejected_inputs_dispatched_to_model': 0}
    write(destination / 'scenario.json', result)
    return result


def screenshots(url: str, token: str, destination: Path):
    from playwright.sync_api import sync_playwright

    destination.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1200}, device_scale_factor=1)
        page.goto(url, wait_until='networkidle')
        page.locator('#api-token').fill(token)
        page.locator('#sms-text').fill('Congratulations! You won a free cash prize. Call now to claim your reward!')
        with page.expect_response(lambda r: r.url.endswith('/predict') and r.request.method == 'POST') as event:
            page.locator('#submit-button').click()
        response = event.value
        if response.status != 200:
            raise RuntimeError('Browser prediction failed')
        page.wait_for_selector('#status[data-state="success"]')
        page.locator('#api-token').fill('')
        page.screenshot(path=str(destination / 'success.png'), full_page=True)
        page.locator('#api-token').fill('invalid-demo-credential')
        with page.expect_response(lambda r: r.url.endswith('/predict') and r.request.method == 'POST') as event:
            page.locator('#submit-button').click()
        if event.value.status != 401:
            raise RuntimeError('Browser error state did not reject the credential')
        page.wait_for_selector('#status[data-state="error"]')
        page.locator('#api-token').fill('')
        page.screenshot(path=str(destination / 'unauthorized.png'), full_page=True)
        write(destination / 'browser-check.json', {'passed': True, 'browser_version': browser.version,
              'prediction_http_status': response.status, 'unauthorized_http_status': event.value.status,
              'token_field_cleared_before_capture': True})
        browser.close()


def check_detection(destination: Path, log_text: str, result: dict):
    from src.detection import detect

    records = []
    for line in log_text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and 'timestamp' in row:
            records.append(row)
    (destination / 'requests.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in records))
    rule = json.loads((ROOT / 'config/detection.json').read_text())
    finding = detect(records, rule, result['start_utc'], result['end_utc'])
    if not finding['triggered'] or finding['observed'] != 3:
        raise RuntimeError('Detection rule did not match the actual service log')
    finding.update(normal_before_http_status=200, normal_after_http_status=result['recovered_http_status'],
                   limitations='Application-level authentication failures only; no claim about poisoning or model accuracy')
    write(destination / 'detection.json', finding)


def verify_no_secrets(destination: Path, tokens: tuple[str, str]):
    for path in destination.rglob('*'):
        if path.is_file() and path.suffix not in {'.png', '.zip'}:
            if any(token.encode() in path.read_bytes() for token in tokens):
                raise RuntimeError('Runtime credential found in diagnostic output')


def local(destination: Path, capture_screenshots: bool):
    token, monitoring = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    port = free_port()
    url = f'http://127.0.0.1:{port}'
    model = Path(os.environ.get('ML_MODEL_PATH', str(ROOT / 'artifacts/ci/model.skops')))
    reference = Path(os.environ.get('ML_MODEL_REFERENCE', str(ROOT / 'artifacts/ci/model-manifest.json')))
    env = {**os.environ, 'ML_API_TOKEN': token, 'ML_METRICS_TOKEN': monitoring, 'ML_RATE_LIMIT': '10',
           'ML_RATE_PERIOD_SECONDS': '2', 'ML_MODEL_PATH': str(model), 'ML_MODEL_REFERENCE': str(reference)}
    destination.mkdir(parents=True, exist_ok=True)
    log_path = destination / 'service.log'
    with log_path.open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'src.serve', '--port', str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            wait_health(url)
            result = exercise(url, token, monitoring, destination)
            if capture_screenshots:
                screenshots(url, token, destination / 'screenshots')
            check_detection(destination, log_path.read_text(), result)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    # Separate process with a modified copy: the preserved model and reference are never changed.
    with tempfile.TemporaryDirectory(prefix='ml-lab4-tamper-') as temp:
        damaged = Path(temp) / 'modified-copy.skops'
        damaged.write_bytes(model.read_bytes() + b'X')
        env['ML_MODEL_PATH'] = str(damaged)
        with (destination / 'integrity-service.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'src.serve', '--port', str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                response = wait_health(url, 503)
                with httpx.Client(trust_env=False) as client:
                    prediction = client.post(url + '/predict', headers={'Authorization': 'Bearer ' + token}, json={'text': 'Hi'})
                if prediction.status_code != 503:
                    raise RuntimeError('Damaged model allowed prediction')
                write(destination / 'integrity-probe.json', {'passed': True, 'modified_copy_only': True,
                      'health_status': response.status_code, 'health_body': response.json(), 'predict_status': prediction.status_code,
                      'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(), 'reference_unchanged': True})
            finally:
                process.terminate()
                process.wait(timeout=10)
    verify_no_secrets(destination, (token, monitoring))
    return {'passed': True, 'mode': 'local', 'screenshots': capture_screenshots,
            'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest()}


def container(destination: Path):
    token, monitoring = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    destination.mkdir(parents=True, exist_ok=True)
    cid = None
    with tempfile.TemporaryDirectory(prefix='ml-lab4-runtime-') as temp:
        secret_file = Path(temp) / 'runtime.env'
        secret_file.write_text(f'ML_API_TOKEN={token}\nML_METRICS_TOKEN={monitoring}\nML_RATE_LIMIT=10\nML_RATE_PERIOD_SECONDS=2\n')
        secret_file.chmod(0o600)
        try:
            cid = run(['docker', 'run', '-d', '--rm', '--init', '--read-only', '--cap-drop=ALL',
                       '--security-opt=no-new-privileges', '--pids-limit=64', '--memory=512m', '--cpus=1',
                       '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m', '--env-file', str(secret_file),
                       '-p', '127.0.0.1::8000', 'ml-project:lab3'])
            ports = json.loads(run(['docker', 'inspect', '--format', '{{json .NetworkSettings.Ports}}', cid]))
            binding = ports['8000/tcp'][0]
            if binding['HostIp'] != '127.0.0.1':
                raise RuntimeError('Application port is not limited to loopback')
            url = 'http://127.0.0.1:' + binding['HostPort']
            wait_health(url)
            uid = int(run(['docker', 'exec', cid, 'id', '-u']))
            writable = run(['docker', 'exec', cid, 'python', '-c',
                            'import os; print(os.access("/app/security/model-manifest-lab2-v1.json",os.W_OK))'])
            if uid == 0 or writable != 'False':
                raise RuntimeError('Container privilege or model reference policy failed')
            result = exercise(url, token, monitoring, destination)
            # Docker logs written to stderr are captured explicitly as well.
            completed = subprocess.run(['docker', 'logs', cid], check=True, capture_output=True, text=True, timeout=10)
            log_text = completed.stdout + completed.stderr
            check_detection(destination, log_text, result)
            write(destination / 'container-runtime.json', {'passed': True, 'uid': uid, 'model_reference_writable': False,
                  'host_binding': binding['HostIp'], 'container_port': 8000, 'read_only': True,
                  'cap_drop': ['ALL'], 'no_new_privileges': True, 'memory_bytes': 512 * 1024 * 1024,
                  'cpus': 1, 'pids_limit': 64, 'secrets_in_image': False, 'secrets_in_report': False})
        finally:
            if cid:
                run(['docker', 'stop', '--time', '5', cid])
    verify_no_secrets(destination, (token, monitoring))
    return {'passed': True, 'mode': 'container', 'uid': uid, 'loopback_only': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['local', 'container'])
    parser.add_argument('--screenshots', action='store_true')
    args = parser.parse_args()
    destination = ROOT / 'reports/lab4' / args.mode
    try:
        result = local(destination, args.screenshots) if args.mode == 'local' else container(destination)
    except Exception as exc:
        write(destination / 'status.json', {'passed': False, 'error_type': type(exc).__name__})
        print('Lab4 verification failed: ' + type(exc).__name__ + '. Inspect the diagnostic reports.', file=sys.stderr)
        return 1
    result.setdefault('model_sha256', hashlib.sha256((ROOT / 'artifacts/ci/model.skops').read_bytes()).hexdigest() if args.mode == 'container' else None)
    checkout = run(['git', 'rev-parse', 'HEAD'])
    source = os.environ.get('ML_LAB4_SOURCE_COMMIT', checkout)
    if not re.fullmatch('[0-9a-f]{40}', source):
        raise ValueError('Invalid source provenance')
    result.update(checked_at_utc=datetime.now(timezone.utc).isoformat(), commit=source, target_checkout_commit=checkout)
    write(destination / 'status.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
