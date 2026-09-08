"""Measure the endpoint the whole project is built around.

`POST /documents/{id}/complete` must return 202 in under 200 ms at p95. The number that goes in
the report comes from Sowmya's Locust run against the deployed service with a deep queue - this
script is the *floor*: the API's own work, in-process, with the stub repository and no network,
no S3, no SQS, no database.

Read it as "the handler itself costs about X" and nothing more. It cannot tell you what the
service does under load, and saying otherwise in the report would be dishonest.

    python tests/bench/bench_submit.py --iterations 500
"""

from __future__ import annotations

import argparse
import hashlib
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("JWT_SECRET", "bench-only-not-a-real-secret")
os.environ.setdefault("SQS_QUEUE_URL", "")  # no AWS: this measures our code, not theirs
# A log line per request would otherwise be part of what we time.
os.environ.setdefault("LOG_LEVEL", "WARNING")


class _FakeS3:
    """Stands in for boto3's presigner. Measuring S3's latency here would be measuring AWS."""

    def generate_presigned_post(self, Bucket, Key, Fields, Conditions, ExpiresIn):  # noqa: N803
        return {"url": f"https://s3.local/{Bucket}", "fields": {"key": Key, **Fields}}


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank. With a few hundred samples, interpolating invents precision we do not have."""
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[idx]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=25)
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    from services.common import aws

    aws.s3 = lambda: _FakeS3()

    from services.api.deps import set_repo
    from services.api.main import app
    from services.api.repo import InMemoryRepo

    set_repo(InMemoryRepo())
    client = TestClient(app)

    token = client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@occdesk.example", "password": "occdesk-local"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    samples: list[float] = []
    for i in range(args.warmup + args.iterations):
        sha = hashlib.sha256(f"bench-{i}".encode()).hexdigest()
        doc_id = client.post(
            "/api/v1/documents/upload-url",
            json={"filename": f"{i}.pdf", "byte_size": 1_843_200, "sha256": sha},
            headers=headers,
        ).json()["document_id"]

        started = time.perf_counter()
        response = client.post(f"/api/v1/documents/{doc_id}/complete", headers=headers)
        elapsed_ms = (time.perf_counter() - started) * 1000

        assert response.status_code == 202, response.text
        if i >= args.warmup:
            samples.append(elapsed_ms)

    print(f"n={len(samples)}  (warmup {args.warmup} discarded, in-process, stub repository)")
    print(f"  mean {statistics.fmean(samples):7.2f} ms")
    print(f"  p50  {percentile(samples, 50):7.2f} ms")
    print(f"  p95  {percentile(samples, 95):7.2f} ms")
    print(f"  p99  {percentile(samples, 99):7.2f} ms")
    print(f"  max  {max(samples):7.2f} ms")
    print("\nFloor only: no network, no S3, no SQS, no database. The number that goes in the")
    print("report is Sowmya's, measured against the deployed service with a deep queue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
