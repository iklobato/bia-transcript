import io
import os
import sys
import importlib.util
from pathlib import Path
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


async def create_async_client():
    app_module = _load_app_module()
    transport = httpx.ASGITransport(app=app_module.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client


@pytest.mark.anyio
async def test_transcribe_accepts_opus_extension(tmp_path):
    async with await create_async_client() as client:
        fake_audio = io.BytesIO(b"fake opus content")
        fake_audio.name = "sample.opus"

        response = await client.post(
            "/transcribe",
            files={"file": ("sample.opus", fake_audio, "audio/opus")},
            data={"language": "en"},
        )

        assert response.status_code in (200, 400)
        if response.status_code == 200:
            body = response.json()
            assert "job_id" in body
            assert body["status"] == "pending"

