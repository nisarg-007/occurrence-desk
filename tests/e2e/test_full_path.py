"""The project's smoke alarm: one test, the whole path, real containers.

Upload -> queued -> parsed -> in the worklist -> priority matches the formula -> disposition
changes the state. It runs in CI on every push to `main` once Wasim's compose stack and Smit's
worker exist; until then it skips loudly rather than passing vacuously.

Run it against a running stack:  E2E_BASE_URL=http://localhost:8000 pytest tests/e2e -q
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import httpx
import pytest

BASE_URL = os.getenv("E2E_BASE_URL")
SAMPLE = Path(__file__).parent / "fixtures" / "nmac.pdf"

pytestmark = pytest.mark.skipif(
    not BASE_URL, reason="set E2E_BASE_URL to run the end-to-end path against a live stack"
)


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    with httpx.Client(base_url=f"{BASE_URL}/api/v1", timeout=30) as c:
        r = c.post(
            "/auth/login",
            json={"email": "analyst@occdesk.example", "password": os.environ["E2E_PASSWORD"]},
        )
        r.raise_for_status()
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c


def _submit(api: httpx.Client, blob: bytes, name: str) -> int:
    sha = hashlib.sha256(blob).hexdigest()
    reserved = api.post(
        "/documents/upload-url",
        json={"filename": name, "byte_size": len(blob), "sha256": sha},
    ).json()
    if not reserved["duplicate"]:
        httpx.post(
            reserved["url"],
            data=reserved["fields"],
            files={"file": (name, blob, "application/pdf")},
            timeout=60,
        ).raise_for_status()
    accepted = api.post(f"/documents/{reserved['document_id']}/complete")
    assert accepted.status_code == 202
    return reserved["document_id"]


def _await_parsed(api: httpx.Client, document_id: int, timeout_s: int = 180) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        doc = api.get(f"/documents/{document_id}").json()
        if doc["status"] == "parsed":
            return doc
        assert doc["status"] != "failed", f"parse failed: {doc['error_text']}"
        time.sleep(2)
    pytest.fail(f"document {document_id} was not parsed within {timeout_s}s")


@pytest.mark.skipif(not SAMPLE.exists(), reason="drop an ASRS report set at tests/e2e/fixtures/")
def test_upload_parse_rank_dispose(api: httpx.Client):
    blob = SAMPLE.read_bytes()
    doc = _await_parsed(api, _submit(api, blob, "nmac.pdf"))
    assert doc["reports"], "a parsed report set must yield reports"

    report_id = doc["reports"][0]["id"]
    listed = api.get("/reports?page_size=200").json()["items"]
    row = next(r for r in listed if r["id"] == report_id)

    why = api.get(f"/reports/{report_id}/why").json()
    assert round(100 * sum(t["product"] for t in why["terms"])) == row["priority"]

    assert (
        api.post(f"/reports/{report_id}/disposition", json={"state": "triaged"}).status_code == 201
    )
    assert api.get(f"/reports/{report_id}").json()["state"] == "triaged"


@pytest.mark.skipif(not SAMPLE.exists(), reason="drop an ASRS report set at tests/e2e/fixtures/")
def test_same_pdf_twice_yields_one_document_and_one_report_set(api: httpx.Client):
    """Duplicate submission is normal, not exceptional. This is in our success criteria."""
    blob = SAMPLE.read_bytes()
    first = _await_parsed(api, _submit(api, blob, "nmac.pdf"))
    second_id = _submit(api, blob, "nmac-again.pdf")
    assert second_id == first["id"], "documents.sha256 must collapse the duplicate to one row"
    acns = [r["acn"] for r in api.get(f"/documents/{second_id}").json()["reports"]]
    assert len(acns) == len(set(acns)), "reports.acn must collapse re-extraction to one row"
