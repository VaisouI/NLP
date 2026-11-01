import asyncio
import sys
from dataclasses import replace

import pytest

from src.inference_process import InferenceProcess, InferenceTimeout, InferenceUnavailable
from tests.test_api import api_project as api_project, settings as settings


def test_inference_deadline_kills_process_and_recovers(api_project):
    async def run():
        worker = InferenceProcess(replace(api_project, inference_timeout_seconds=.05))
        # A controlled non-computing worker demonstrates server-side termination.
        sleeping = await asyncio.create_subprocess_exec(sys.executable, '-c', 'import time; time.sleep(60)',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        worker.process, worker._ready = sleeping, True
        try:
            with pytest.raises(InferenceTimeout):
                await worker.predict({'text': 'meeting at noon'})
            assert sleeping.returncode is not None and sleeping.returncode != 0
            assert worker.terminations == 1
            await asyncio.wait_for(worker.recovery, 10)
            assert worker.ready and worker.process.pid != sleeping.pid
            assert (await worker.predict({'text': 'meeting at noon'}))['prediction'] == 'ham'
        finally:
            await worker.close()
        assert worker.process is None
    asyncio.run(run())


def test_startup_deadline_also_reaps_the_child(api_project, monkeypatch):
    async def run():
        sleeping = await asyncio.create_subprocess_exec(sys.executable, '-c', 'import time; time.sleep(60)',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)

        async def controlled_child(*args, **kwargs):
            return sleeping

        monkeypatch.setattr(asyncio, 'create_subprocess_exec', controlled_child)
        worker = InferenceProcess(replace(api_project, startup_timeout_seconds=.02))
        with pytest.raises(InferenceUnavailable):
            await worker.start()
        assert sleeping.returncode is not None and not worker.ready and worker.process is None
    asyncio.run(run())
