"""Логи без входов и секретов; только ограниченные значения labels."""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

ROUTES = frozenset({'/', '/predict', '/health', '/metrics', '/static/app.js', '/static/style.css'})
LOGGER = logging.getLogger('ml_api')


class Observability:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.requests = Counter('ml_api_requests_total', 'Completed HTTP requests', ['route', 'status'], registry=self.registry)
        self.duration = Histogram('ml_api_request_duration_seconds', 'HTTP response duration', ['route'],
                                  buckets=(.005, .01, .025, .05, .1, .25, .5, 1, 2, 5, 20), registry=self.registry)
        self.rejections = Counter('ml_api_rejections_total', 'Requests rejected by server policy', ['reason'], registry=self.registry)
        self.inference = Counter('ml_api_inference_total', 'Requests dispatched to the inference worker', registry=self.registry)
        self.ready = Gauge('ml_api_model_ready', 'One only while verified model is ready', registry=self.registry)

    def export(self, ready: bool) -> bytes:
        self.ready.set(int(ready))
        return generate_latest(self.registry)


class HttpMiddleware:
    """Ограничивает число незавершённых HTTP-запросов до чтения тела."""
    def __init__(self, app, settings, observations):
        self.app, self.settings, self.observations = app, settings, observations
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        state = scope.setdefault('state', {})
        state['request_id'] = uuid.uuid4().hex
        state['failure_type'] = 'none'
        route = scope['path'] if scope['path'] in ROUTES else 'other'
        started = time.monotonic()
        status, sent = 500, False
        admitted = self.active < self.settings.max_http_inflight
        if admitted:
            self.active += 1

        async def observe_send(message):
            nonlocal status, sent
            if message['type'] == 'http.response.start':
                status, sent = message['status'], True
                headers = list(message.get('headers', []))
                headers.extend([(b'x-request-id', state['request_id'].encode()),
                                (b'x-content-type-options', b'nosniff'), (b'cache-control', b'no-store'),
                                (b'referrer-policy', b'no-referrer'), (b'x-frame-options', b'DENY'),
                                (b'content-security-policy', b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")])
                message = {**message, 'headers': headers}
            await send(message)

        try:
            if not admitted:
                from starlette.responses import JSONResponse
                state['failure_type'] = 'http_capacity'
                await JSONResponse({'error': {'code': 'http_capacity', 'message': 'Server is busy'},
                                    'request_id': state['request_id']}, status_code=503,
                                   headers={'Retry-After': '1'})(scope, receive, observe_send)
            else:
                await self.app(scope, receive, observe_send)
        except Exception:
            state['failure_type'] = 'internal_error'
            if not sent:
                from starlette.responses import JSONResponse
                await JSONResponse({'error': {'code': 'internal_error', 'message': 'Request could not be completed'},
                                    'request_id': state['request_id']}, status_code=500)(scope, receive, observe_send)
        finally:
            if admitted:
                self.active -= 1
            elapsed = time.monotonic() - started
            obs = self.observations
            obs.requests.labels(route, str(status)).inc()
            obs.duration.labels(route).observe(elapsed)
            if state['failure_type'] != 'none':
                obs.rejections.labels(state['failure_type']).inc()
            LOGGER.info(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(),
                                   'request_id': state['request_id'], 'route': route, 'http_status': status,
                                   'duration_ms': round(elapsed * 1000, 3), 'model_version': 'lab2-v1',
                                   'failure_type': state['failure_type']}, allow_nan=False))
