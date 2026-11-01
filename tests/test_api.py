import asyncio
import hashlib
import json
import logging
import secrets
from dataclasses import replace

import httpx
import pytest
import sklearn
import skops.io as sio
from fastapi.testclient import TestClient

from src.api import create_app
from src.api_settings import Settings
from src.preprocessing import NORMALIZATION_VERSION, read_config
from src.splitting import canonical_json
from src.training import build_pipeline


class FakeEngine:
    model_version = 'lab2-v1'

    def __init__(self, settings):
        self.ready = False
        self.calls = []
        self.lock = asyncio.Lock()

    async def start(self):
        self.ready = True

    async def close(self):
        self.ready = False

    async def predict(self, payload):
        self.calls.append(payload)
        return {'prediction': 'ham', 'model_version': self.model_version}


@pytest.fixture
def settings():
    return Settings(api_token=secrets.token_urlsafe(32), metrics_token=secrets.token_urlsafe(32), rate_limit=100)


@pytest.fixture
def api(settings):
    app = create_app(settings, FakeEngine)
    with TestClient(app) as client:
        yield client, app.state.engine, app


def auth(settings):
    return {'Authorization': 'Bearer ' + settings.api_token}


def test_health_page_and_static_are_available(api):
    client, _, _ = api
    assert client.get('/health').json() == {'status': 'healthy', 'model_version': 'lab2-v1'}
    assert client.get('/').status_code == 200
    assert '<html lang="ru">' in client.get('/').text
    script = client.get('/static/app.js')
    assert script.status_code == 200
    assert 'innerHTML' not in script.text and 'localStorage' not in script.text
    assert client.get('/static/style.css').status_code == 200
    assert client.get('/static/../../config/lab2.json').status_code == 404


def test_valid_prediction_has_version_and_server_request_id(api, settings):
    client, engine, _ = api
    response = client.post('/predict', json={'text': 'Meeting at noon'}, headers=auth(settings))
    assert response.status_code == 200
    assert set(response.json()) == {'prediction', 'model_version', 'request_id'}
    assert response.json()['prediction'] == 'ham'
    assert response.json()['request_id'] == response.headers['x-request-id']
    assert len(response.json()['request_id']) == 32
    assert engine.calls == [{'text': 'Meeting at noon'}]
    assert 'default-src' in response.headers['content-security-policy']


@pytest.mark.parametrize('credential', [None, 'Bearer invalid', 'Basic dGVzdA=='])
def test_unauthorized_never_calls_model(api, credential):
    client, engine, _ = api
    response = client.post('/predict', content=b'not JSON', headers={'Authorization': credential} if credential else {})
    assert response.status_code == 401
    assert response.headers['www-authenticate'] == 'Bearer'
    assert engine.calls == []


def test_multiple_authorization_headers_are_rejected(api, settings):
    client, engine, _ = api
    response = client.post('/predict', json={'text': 'Hi'}, headers=[('Authorization', 'Bearer ' + settings.api_token)] * 2)
    assert response.status_code == 401
    assert engine.calls == []


@pytest.mark.parametrize('payload', [{}, [], None, {'text': ''}, {'text': ' \t '}, {'text': None},
                                     {'text': 1}, {'text': True}, {'text': ['hello']},
                                     {'text': 'hello', 'extra': 1}, {'text': '\x00bad'}, {'text': '\ud800'}])
def test_invalid_schema_is_rejected_before_model(api, settings, payload):
    client, engine, _ = api
    response = client.post('/predict', content=json.dumps(payload), headers={**auth(settings), 'Content-Type': 'application/json'})
    assert response.status_code == 422
    assert engine.calls == []


@pytest.mark.parametrize('raw', [b'{', b'\xff', b'{"text":"a","text":"b"}', b'{"text":NaN}', b'{"text":Infinity}'])
def test_invalid_json_is_rejected_before_model(api, settings, raw):
    client, engine, _ = api
    response = client.post('/predict', content=raw, headers={**auth(settings), 'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert engine.calls == []


@pytest.mark.parametrize('extra', [{'Content-Type': 'text/plain'}, {'Content-Type': 'multipart/form-data'},
                                  {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}])
def test_unsupported_media_is_rejected(api, settings, extra):
    client, engine, _ = api
    assert client.post('/predict', content=b'{}', headers={**auth(settings), **extra}).status_code == 415
    assert engine.calls == []


@pytest.mark.parametrize('payload', [{'text': 'a' * 4097}, {'text': '\ufdfa' * 300}])
def test_decoded_and_normalized_limits_are_enforced(api, settings, payload):
    client, engine, _ = api
    raw = json.dumps(payload).encode()
    assert len(raw) < settings.max_body_bytes
    assert client.post('/predict', content=raw, headers={**auth(settings), 'Content-Type': 'application/json'}).status_code == 413
    assert engine.calls == []


def test_content_length_shortcut_and_metrics_auth(api, settings):
    client, engine, _ = api
    response = client.post('/predict', content=b' ' * (settings.max_body_bytes + 1),
                           headers={**auth(settings), 'Content-Type': 'application/json'})
    assert response.status_code == 413
    assert engine.calls == []
    assert client.get('/metrics').status_code == 401
    assert client.get('/metrics', headers=auth(settings)).status_code == 401
    assert client.get('/metrics', headers={'Authorization': 'Bearer ' + settings.metrics_token}).status_code == 200


async def raw_request(app, settings, chunks, length=None, delay=0):
    headers = [(b'authorization', ('Bearer ' + settings.api_token).encode()), (b'content-type', b'application/json')]
    if length is not None:
        headers.append((b'content-length', length))
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
             'scheme': 'http', 'path': '/predict', 'raw_path': b'/predict', 'query_string': b'', 'headers': headers,
             'client': ('127.0.0.1', 1234), 'server': ('127.0.0.1', 8000)}
    messages, consumed = [], []

    async def receive():
        if delay:
            await asyncio.sleep(delay)
        if len(consumed) < len(chunks):
            i = len(consumed)
            consumed.append(i)
            return {'type': 'http.request', 'body': chunks[i], 'more_body': i < len(chunks) - 1}
        return {'type': 'http.disconnect'}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return next(m['status'] for m in messages if m['type'] == 'http.response.start'), consumed


@pytest.mark.parametrize('length', [None, b'1'])
def test_stream_limit_without_or_with_lying_content_length(settings, length):
    async def run():
        app = create_app(settings, FakeEngine)
        async with app.router.lifespan_context(app):
            code, consumed = await raw_request(app, settings, [b'x' * 8192] * 10, length)
            assert code == 413
            assert len(consumed) == 5  # Stops before loading the complete body.
            assert app.state.engine.calls == []
    asyncio.run(run())


def test_slow_stream_deadline_is_enforced(settings):
    async def run():
        limits = replace(settings, body_timeout_seconds=.02)
        app = create_app(limits, FakeEngine)
        async with app.router.lifespan_context(app):
            code, consumed = await raw_request(app, limits, [b'{}'], delay=.1)
            assert code == 408 and consumed == [] and app.state.engine.calls == []
    asyncio.run(run())


def test_rate_limit_and_recovery_ignore_forwarded_headers(settings):
    async def run():
        limited = replace(settings, rate_limit=2, rate_period_seconds=.05)
        app = create_app(limited, FakeEngine)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            for _ in range(2):
                assert (await client.post('/predict', json={'text': 'Hello'}, headers=auth(limited))).status_code == 200
            response = await client.post('/predict', json={'text': 'Hello'}, headers={**auth(limited), 'X-Forwarded-For': '198.51.100.1'})
            assert response.status_code == 429 and int(response.headers['retry-after']) >= 1
            assert len(app.state.engine.calls) == 2
            await asyncio.sleep(.07)
            assert (await client.post('/predict', json={'text': 'Hello'}, headers=auth(limited))).status_code == 200
    asyncio.run(run())


def test_invalid_credentials_have_bounded_global_bucket(settings):
    app = create_app(replace(settings, invalid_auth_limit=2), FakeEngine)
    with TestClient(app) as client:
        assert [client.post('/predict').status_code for _ in range(3)] == [401, 401, 429]
        assert app.state.engine.calls == []


@pytest.mark.parametrize('capacity,second_route,expected', [(16, '/predict', 503), (1, '/health', 503)])
def test_parallelism_is_bounded_without_waiting_queue(settings, capacity, second_route, expected):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class BusyEngine(FakeEngine):
            async def predict(self, payload):
                async with self.lock:
                    self.calls.append(payload)
                    entered.set()
                    await release.wait()
                    return {'prediction': 'ham', 'model_version': self.model_version}

        app = create_app(replace(settings, max_http_inflight=capacity), BusyEngine)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            pending = asyncio.create_task(client.post('/predict', json={'text': 'Hi'}, headers=auth(settings)))
            await asyncio.wait_for(entered.wait(), 1)
            second = await (client.post(second_route, json={'text': 'Hi'}, headers=auth(settings)) if second_route == '/predict' else client.get(second_route))
            assert second.status_code == expected and len(app.state.engine.calls) == 1
            release.set()
            assert (await pending).status_code == 200
            assert (await client.get('/health')).status_code == 200
    asyncio.run(run())


def test_logs_and_metric_labels_do_not_contain_inputs_credentials_or_paths(api, settings, caplog):
    client, _, app = api
    caplog.set_level(logging.INFO, logger='ml_api')
    marker = 'private-message-marker-98765'
    client.post('/predict', json={'text': marker}, headers={**auth(settings), 'X-Request-ID': marker})
    client.get('/private-name?token=' + marker)
    logs = [json.loads(record.message) for record in caplog.records if record.name == 'ml_api']
    assert {row['route'] for row in logs} == {'/predict', 'other'}
    assert all(set(row) == {'timestamp', 'request_id', 'route', 'http_status', 'duration_ms', 'model_version', 'failure_type'} for row in logs)
    combined = caplog.text + app.state.observations.export(True).decode()
    assert all(secret not in combined for secret in [marker, settings.api_token, settings.metrics_token, '/private-name'])
    for family in app.state.observations.registry.collect():
        for sample in family.samples:
            assert set(sample.labels) <= {'route', 'status', 'reason', 'le'}


@pytest.fixture
def api_project(tmp_path, settings):
    root = tmp_path
    (root / 'config').mkdir()
    config = read_config()
    config['tfidf']['min_df'] = 1
    (root / 'config/lab2.json').write_bytes(canonical_json(config))
    model = build_pipeline(config)
    model.fit(['meeting at noon', 'call me tomorrow', 'free cash winner', 'claim free prize'], ['ham', 'ham', 'spam', 'spam'])
    model_path = root / 'model.skops'
    sio.dump(model, model_path)
    reference = root / 'manifest.json'
    reference.write_text(json.dumps({'format': 'skops', 'model_version': 'lab2-v1',
        'sha256': hashlib.sha256(model_path.read_bytes()).hexdigest(), 'bytes': model_path.stat().st_size,
        'normalization_version': NORMALIZATION_VERSION, 'sklearn_version': sklearn.__version__,
        'config_sha256': hashlib.sha256(canonical_json(config)).hexdigest()}))
    # Worker imports source from the real project; its configuration root is independently passed.
    return replace(settings, model_path=model_path, reference_path=reference, project_root=root)


@pytest.mark.parametrize('damage', ['hash', 'missing', 'version'])
def test_failed_model_load_never_reports_healthy(api_project, damage):
    if damage == 'hash':
        api_project.model_path.write_bytes(api_project.model_path.read_bytes() + b'X')
    elif damage == 'missing':
        api_project.model_path.unlink()
    else:
        record = json.loads(api_project.reference_path.read_text())
        record['sklearn_version'] = '0.0.0'
        api_project.reference_path.write_text(json.dumps(record))
    app = create_app(api_project)
    with TestClient(app) as client:
        response = client.get('/health')
        assert response.status_code == 503 and response.json()['status'] == 'unavailable'
        assert client.post('/predict', json={'text': 'Hi'}, headers=auth(api_project)).status_code == 503
        assert str(api_project.project_root) not in response.text


def test_actual_model_worker_is_reused_for_predictions(api_project):
    app = create_app(api_project)
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        pid = app.state.engine.process.pid
        response = client.post('/predict', json={'text': 'claim free prize'}, headers=auth(api_project))
        assert response.status_code == 200 and response.json()['prediction'] == 'spam'
        assert client.post('/predict', json={'text': 'meeting at noon'}, headers=auth(api_project)).json()['prediction'] == 'ham'
        assert app.state.engine.process.pid == pid


def test_runtime_credentials_are_required_and_hidden(settings, monkeypatch):
    assert settings.api_token not in repr(settings) and settings.metrics_token not in repr(settings)
    for key in ('ML_API_TOKEN', 'ML_METRICS_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match='tokens'):
        Settings.from_env()
    with pytest.raises(ValueError, match='differ'):
        replace(settings, metrics_token=settings.api_token)
