import io
import os
import sys
import json
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import httpx


def _load_app_module():
    os.environ["SKIP_VOSK_LOAD"] = "1"
    os.environ["DISABLE_QUEUE_PROCESSOR"] = "1"
    project_root = Path(__file__).resolve().parents[1]
    app_path = project_root / "app.py"
    spec = importlib.util.spec_from_file_location("app", str(app_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules["app"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def make_async_client_and_api():
    app_module = _load_app_module()
    transport = httpx.ASGITransport(app=app_module.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client, app_module.api


@pytest.mark.anyio
async def test_processing_pipeline_with_mocks(tmp_path):
    client, api = await make_async_client_and_api()

    # Prepare fake upload
    fake_audio = io.BytesIO(b"fake opus content")
    fake_audio.name = "audio.opus"

    # Mock ffmpeg conversion function by patching subprocess.run to create a dummy wav
    def fake_subprocess_run(cmd, stdout=None, stderr=None):
        # Last arg is the output wav path
        out_wav = cmd[-1]
        with open(out_wav, "wb") as f:
            f.write(b"RIFF\x00\x00\x00\x00WAVEfmt ")
        m = MagicMock()
        m.returncode = 0
        m.stdout = b""
        m.stderr = b""
        return m

    # Mock soundfile.read to return small int16 array and samplerate
    import numpy as np

    def fake_sf_read(path, dtype=None):
        data = (np.zeros(8000)).astype(np.int16)
        return data, 16000

    # Mock Vosk recognizer to return predictable results
    class FakeRecognizer:
        def __init__(self, model, samplerate):
            pass

        def SetWords(self, value):
            pass

        def AcceptWaveform(self, chunk):
            return False

        def Result(self):
            return json.dumps({"text": ""})

        def FinalResult(self):
            return json.dumps({
                "text": "hello world",
                "result": [
                    {"start": 0.0, "end": 1.0, "word": "hello"},
                    {"start": 1.0, "end": 2.0, "word": "world"},
                ],
            })

    with patch("subprocess.run", side_effect=fake_subprocess_run), \
         patch("soundfile.read", side_effect=fake_sf_read), \
         patch("app.KaldiRecognizer", FakeRecognizer), \
         patch("app.vosk_model", object()):  # pretend model exists

        # Submit job
        r = await client.post(
            "/transcribe",
            files={"file": ("audio.opus", fake_audio, "audio/opus")},
            data={"language": "en"},
        )
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        # Manually pull a job from the queue and process it synchronously
        # since the background queue is disabled in tests
        from app import job_queue
        job = job_queue.jobs[job_id]

        # Run the processing coroutine directly
        import asyncio

        await api.process_transcription_job(job)

        # Verify completion
        status = await client.get(f"/jobs/{job_id}")
        assert status.status_code == 200
        payload = status.json()
        assert payload["status"] == "completed"
        assert payload["result"]["transcript"] == "hello world"

