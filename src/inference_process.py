"""Один persistent worker, нулевая очередь и принудительное завершение по deadline."""
from __future__ import annotations

import asyncio
import json
import os
import sys

from src.api_settings import Settings
from src.artifacts import ROOT


class InferenceUnavailable(RuntimeError):
    pass


class InferenceBusy(RuntimeError):
    pass


class InferenceTimeout(RuntimeError):
    pass


class InferenceProcess:
    model_version = 'lab2-v1'

    def __init__(self, settings: Settings):
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.recovery: asyncio.Task | None = None
        self._ready = False
        self.closed = False
        self.terminations = 0

    @property
    def ready(self) -> bool:
        return self._ready and self.process is not None and self.process.returncode is None

    async def start(self) -> None:
        self._ready = False
        env = {key: value for key, value in os.environ.items() if key not in {'ML_API_TOKEN', 'ML_METRICS_TOKEN'}}
        env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'src.inference_worker', '--model', str(self.settings.model_path),
            '--reference', str(self.settings.reference_path), '--root', str(self.settings.project_root),
            cwd=ROOT, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=4096)
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), self.settings.startup_timeout_seconds)
            result = json.loads(line)
            if result != {'ready': True, 'model_version': self.model_version}:
                raise InferenceUnavailable('Model is not ready')
            self._ready = True
        except (ValueError, OSError, asyncio.TimeoutError, InferenceUnavailable) as exc:
            await self._terminate()
            raise InferenceUnavailable('Model is not ready') from exc

    async def _terminate(self) -> None:
        self._ready = False
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                    self.terminations += 1
                except ProcessLookupError:
                    pass
            await process.wait()

    async def _recover(self) -> None:
        async with self.lock:
            if not self.closed:
                try:
                    await self.start()
                except (OSError, InferenceUnavailable):
                    self._ready = False

    async def predict(self, payload: dict) -> dict:
        if not self.ready:
            raise InferenceUnavailable('Model is not ready')
        if self.lock.locked():
            raise InferenceBusy('Inference slot is occupied')
        async with self.lock:
            try:
                async with asyncio.timeout(self.settings.inference_timeout_seconds):
                    self.process.stdin.write(json.dumps(payload, ensure_ascii=True, allow_nan=False).encode() + b'\n')
                    await self.process.stdin.drain()
                    line = await self.process.stdout.readline()
                result = json.loads(line)
                if (type(result) is not dict or set(result) != {'prediction', 'model_version'}
                        or result['prediction'] not in {'ham', 'spam'} or result['model_version'] != self.model_version):
                    raise InferenceUnavailable('Invalid worker response')
                return result
            except asyncio.TimeoutError as exc:
                await self._terminate()
                self.recovery = asyncio.create_task(self._recover())
                raise InferenceTimeout('Inference deadline exceeded') from exc
            except asyncio.CancelledError:
                await self._terminate()
                self.recovery = asyncio.create_task(self._recover())
                raise
            except (ValueError, OSError, InferenceUnavailable) as exc:
                await self._terminate()
                self.recovery = asyncio.create_task(self._recover())
                raise InferenceUnavailable('Model is not ready') from exc

    async def close(self) -> None:
        self.closed = True
        if self.recovery is not None and not self.recovery.done():
            self.recovery.cancel()
            try:
                await self.recovery
            except asyncio.CancelledError:
                pass
        await self._terminate()
