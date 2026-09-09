from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-not-a-real-one")
os.environ.setdefault("SQS_QUEUE_URL", "")  # no AWS calls in unit or contract tests


@pytest.fixture
def repo():
    from services.api.repo import InMemoryRepo

    # Not the full sample in tests: assertions about ordering and paging should read against
    # the small four-record fixture, not all nineteen real reports.
    return InMemoryRepo(full_sample=False)


@pytest.fixture
def client(repo):
    from fastapi.testclient import TestClient

    from services.api.deps import set_repo
    from services.api.main import app

    set_repo(repo)
    return TestClient(app)


def _token(client, email: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "occdesk-local"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def analyst_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'analyst@occdesk.example')}"}


@pytest.fixture
def manager_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'manager@occdesk.example')}"}
