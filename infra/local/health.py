"""Dependency checks used by Compose; never connect to real AWS."""

import argparse
import os
import time
import urllib.request
from pathlib import Path

import boto3
from botocore.config import Config
from sqlalchemy import create_engine, text


def client(service):
    endpoint = os.environ[f"{service.upper()}_ENDPOINT_URL"]
    if not endpoint.startswith(
        ("http://minio:", "http://elasticmq:", "http://localhost:", "http://127.0.0.1:")
    ):
        raise RuntimeError("Local tooling refuses non-local cloud endpoints")
    return boto3.client(
        service,
        endpoint_url=endpoint,
        region_name="us-east-1",
        config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 0}),
    )


def database():
    engine = create_engine(os.environ["DATABASE_URL"], connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def check(kind):
    if kind in ("dependencies", "api"):
        database()
        client("s3").list_buckets()
        client("sqs").list_queues()
    if kind == "api":
        with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=3) as response:
            if response.status != 200:
                raise RuntimeError("API health endpoint failed")
    # This heartbeat is touched by the main worker loop, not by a side thread.
    if (
        kind == "worker"
        and time.time() - Path("/tmp/occdesk-worker-heartbeat").stat().st_mtime > 120
    ):
        raise RuntimeError("Worker loop heartbeat is stale")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["dependencies", "api", "worker"])
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    deadline = time.monotonic() + (120 if args.wait else 0)
    while True:
        try:
            check(args.kind)
            return
        except Exception as exc:
            if time.monotonic() >= deadline:
                raise SystemExit(f"{args.kind} health check failed: {type(exc).__name__}") from None
            time.sleep(2)


if __name__ == "__main__":
    main()
