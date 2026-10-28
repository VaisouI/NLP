#!/usr/bin/env python3
"""Проверяет модель, защиту эталона и Jupyter, не выводя токен."""
from pathlib import Path
import getpass
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.artifacts import ArtifactError, MODEL_RELATIVE, PROTECTED_REFERENCE, load_verified_model, preferred_reference
from src.prediction import SmsPredictor
from src.training import write_json


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def main():
    if getpass.getuser() != 'mluser' or preferred_reference(ROOT) != PROTECTED_REFERENCE:
        raise SystemExit('Expected mluser and the protected external model reference')
    predictor = SmsPredictor.from_project(ROOT)
    prediction = predictor.predict({'text': 'Project lab2 meeting tomorrow at noon'})
    stat = PROTECTED_REFERENCE.stat()
    protected = stat.st_uid == 0 and stat.st_mode & 0o222 == 0
    if not protected:
        raise SystemExit('Model reference must be owned by root and read-only')
    with tempfile.TemporaryDirectory(prefix='lab2-model-integrity-') as directory:
        copy = Path(directory) / 'changed.skops'
        data = bytearray((ROOT / MODEL_RELATIVE).read_bytes());data[-1] ^= 1;copy.write_bytes(data)
        try:
            load_verified_model(copy, PROTECTED_REFERENCE)
        except ArtifactError as error:
            if 'integrity' not in str(error):raise
            tamper_detected = True
        else:
            raise SystemExit('Changed model was unexpectedly accepted')
    result = subprocess.run([sys.executable, '-m', 'jupyter', 'server', 'list', '--json'], capture_output=True, text=True, check=True)
    servers = []
    for line in result.stdout.splitlines():
        if line.strip().startswith('{'):
            servers.append(json.loads(line))
    candidates = [s for s in servers if urlsplit(s.get('url', '')).hostname in {'localhost', '127.0.0.1', '::1'} and s.get('port') == 8888]
    if not candidates:raise SystemExit('No loopback Jupyter server found for mluser on port 8888')
    server = candidates[0]
    auth_enabled = bool(server.get('token')) or bool(server.get('password'))
    if not auth_enabled:raise SystemExit('Jupyter authentication is not enabled')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        status = opener.open('http://127.0.0.1:8888/api/status', timeout=5).status
    except urllib.error.HTTPError as error:
        status = error.code
    if status not in {302, 401, 403}:raise SystemExit('Unauthenticated Jupyter API request was not rejected')
    safe = {
        'user': getpass.getuser(), 'uid': os.getuid(), 'protected_model_reference': str(PROTECTED_REFERENCE),
        'reference_owned_by_root_read_only': protected, 'model_load_and_prediction_ok': prediction['prediction'] in {'ham', 'spam'},
        'model_tamper_detected': tamper_detected, 'jupyter_host': '127.0.0.1', 'jupyter_port': 8888,
        'jupyter_authentication_enabled': auth_enabled, 'unauthenticated_api_status': status,
        'token_in_report': False,
    }
    write_json(ROOT / 'evidence/lab2/vm/runtime-security.json', safe)
    print(json.dumps(safe, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
