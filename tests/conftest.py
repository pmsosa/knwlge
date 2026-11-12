import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))
os.environ["KNWLGE_NO_WORKER"] = "1"

import fakes  # noqa: E402


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KNWLGE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("KNWLGE_MODE", "personal")   # whatever the live .env says; team tests switch it themselves
    monkeypatch.delenv("KNWLGE_ALLOWED_HOSTS", raising=False)
    from app import db, gemini, verify
    monkeypatch.setattr(gemini, "transport", httpx.MockTransport(fakes.handler))
    monkeypatch.setattr(verify, "transport", httpx.MockTransport(fakes.web))
    monkeypatch.setattr(verify, "resolver", fakes.public_dns)
    fakes.CALLS.clear()
    fakes.OVERRIDES.clear()
    fakes.SEARCH_FAILS["on"] = False
    db.init()
    with db.tx() as c:
        db.set_setting(c, "gemini_api_key", "test-key")
    yield tmp_path


@pytest.fixture()
def client(app_env):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, headers={"x-knwlge": "1"}) as tc:
        yield tc


def drain(max_steps: int = 500) -> int:
    """Run queued jobs and link checks until there's nothing left."""
    from app import jobs, media, verify
    n = 0
    while n < max_steps and (jobs.run_one() or media.step() or verify.step()):
        n += 1
    return n
