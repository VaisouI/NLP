"""Защищённый API SMS-классификатора: потоковые пределы до JSON/model.predict."""
from __future__ import annotations

import asyncio
import json
import math
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse, Response

from src.api_observability import HttpMiddleware, Observability
from src.api_settings import Settings
from src.inference_process import InferenceBusy, InferenceProcess, InferenceTimeout, InferenceUnavailable
from src.preprocessing import InputValidationError, configured_policy, validate_payload

STATIC = Path(__file__).resolve().parents[1] / 'static'


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after


class WindowLimiter:
    """Один bucket на настроенный credential, без словаря произвольных IP/token."""
    def __init__(self, limit: int, period: float):
        self.limit, self.period = limit, period
        self.times = deque(maxlen=limit)

    def consume(self) -> int:
        now = time.monotonic()
        while self.times and self.times[0] <= now - self.period:
            self.times.popleft()
        if len(self.times) >= self.limit:
            return max(1, math.ceil(self.period - (now - self.times[0])))
        self.times.append(now)
        return 0


def authorize(request: Request, expected: str, invalid: WindowLimiter) -> None:
    values = request.headers.getlist('authorization')
    candidate = values[0] if len(values) == 1 else ''
    valid = secrets.compare_digest(candidate.encode('utf-8'), ('Bearer ' + expected).encode('ascii'))
    if not valid:
        retry = invalid.consume()
        if retry:
            raise ApiError(429, 'invalid_auth_rate_limit', 'Too many authentication failures', retry)
        raise ApiError(401, 'unauthorized', 'A valid Bearer token is required')


def strict_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Duplicate JSON field')
        obj[key] = value
    return obj


def reject_constant(value):
    raise ValueError('Non-finite JSON number')


async def read_payload(request: Request, settings: Settings) -> object:
    media = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if media != 'application/json' or request.headers.get('content-encoding', 'identity').lower() != 'identity':
        raise ApiError(415, 'unsupported_media', 'Use uncompressed application/json encoded as UTF-8')
    lengths = request.headers.getlist('content-length')
    if len(lengths) > 1 or lengths and (not 1 <= len(lengths[0]) <= 10 or not lengths[0].isascii() or not lengths[0].isdecimal()):
        raise ApiError(400, 'invalid_length', 'Invalid Content-Length')
    if lengths and int(lengths[0]) > settings.max_body_bytes:
        raise ApiError(413, 'body_too_large', 'Request body exceeds the byte limit')
    body = bytearray()
    try:
        async with asyncio.timeout(settings.body_timeout_seconds):
            async for chunk in request.stream():
                if len(body) + len(chunk) > settings.max_body_bytes:
                    raise ApiError(413, 'body_too_large', 'Request body exceeds the byte limit')
                body.extend(chunk)
    except asyncio.TimeoutError as exc:
        raise ApiError(408, 'body_timeout', 'Request body deadline exceeded') from exc
    try:
        return json.loads(body.decode('utf-8', errors='strict'), object_pairs_hook=strict_object, parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ApiError(400, 'invalid_json', 'Body must be valid UTF-8 JSON with unique fields and finite numbers') from exc


def create_app(settings: Settings | None = None, engine_factory=InferenceProcess) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    policy = configured_policy(settings.project_root)
    engine = engine_factory(settings)
    obs = Observability()
    prediction_limit = WindowLimiter(settings.rate_limit, settings.rate_period_seconds)
    invalid_limit = WindowLimiter(settings.invalid_auth_limit, settings.invalid_auth_period_seconds)

    @asynccontextmanager
    async def lifespan(app):
        try:
            try:
                await engine.start()
            except (OSError, InferenceUnavailable):
                # Keep health available with 503; never reveal paths or traceback.
                obs.ready.set(0)
            yield
        finally:
            await engine.close()

    app = FastAPI(title='Защищённый SMS-фильтр', version='lab4-v1', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine, app.state.observations, app.state.settings = engine, obs, settings
    app.add_middleware(HttpMiddleware, settings=settings, observations=obs)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        request.state.failure_type = exc.code
        headers = {'Retry-After': str(exc.retry_after)} if exc.retry_after is not None else {}
        if exc.status == 401:
            headers['WWW-Authenticate'] = 'Bearer'
        return JSONResponse({'error': {'code': exc.code, 'message': exc.message},
                             'request_id': request.state.request_id}, status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def schema_error(request: Request, exc: RequestValidationError):
        return await api_error(request, ApiError(422, 'invalid_schema', 'Invalid request schema'))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return await api_error(request, ApiError(exc.status_code, 'http_error', 'Unsupported route or method'))

    @app.get('/health')
    async def health(request: Request):
        obs.ready.set(int(engine.ready))
        if not engine.ready:
            request.state.failure_type = 'model_unavailable'
            return JSONResponse({'status': 'unavailable', 'model_version': engine.model_version}, status_code=503)
        return {'status': 'healthy', 'model_version': engine.model_version}

    @app.post('/predict')
    async def predict(request: Request):
        authorize(request, settings.api_token, invalid_limit)
        retry = prediction_limit.consume()
        if retry:
            raise ApiError(429, 'rate_limit', 'Prediction request rate exceeded', retry)
        payload = await read_payload(request, settings)
        try:
            validate_payload(payload, policy)
        except InputValidationError as exc:
            oversized = exc.code in {'text_too_long', 'text_too_large', 'normalized_too_large'}
            raise ApiError(413 if oversized else 422, 'input_limit' if oversized else 'invalid_input', str(exc)) from exc
        if not engine.ready:
            raise ApiError(503, 'model_unavailable', 'Model is not ready')
        try:
            # Busy requests are rejected by the worker before any inference call.
            if engine.lock.locked():
                raise InferenceBusy('Inference slot is occupied')
            obs.inference.inc()
            result = await engine.predict(payload)
        except InferenceBusy as exc:
            raise ApiError(503, 'inference_busy', 'Prediction capacity is occupied', 1) from exc
        except InferenceTimeout as exc:
            raise ApiError(504, 'inference_timeout', 'Prediction deadline exceeded') from exc
        except InferenceUnavailable as exc:
            raise ApiError(503, 'model_unavailable', 'Model is not ready') from exc
        return {**result, 'request_id': request.state.request_id}

    @app.get('/metrics')
    async def metrics(request: Request):
        authorize(request, settings.metrics_token, invalid_limit)
        return Response(obs.export(engine.ready), media_type='text/plain; version=0.0.4; charset=utf-8')

    @app.get('/', include_in_schema=False)
    async def page():
        return FileResponse(STATIC / 'index.html')

    @app.get('/static/app.js', include_in_schema=False)
    async def javascript():
        return FileResponse(STATIC / 'app.js', media_type='application/javascript')

    @app.get('/static/style.css', include_in_schema=False)
    async def stylesheet():
        return FileResponse(STATIC / 'style.css', media_type='text/css')

    return app
