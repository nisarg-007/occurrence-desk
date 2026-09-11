"""Launch the worker with main-loop liveness and visible integration errors."""

import time
from pathlib import Path


def main():
    try:
        from services.worker import store, worker
    except ModuleNotFoundError as exc:
        raise SystemExit(f"Missing worker implementation or dependency: {exc.name}") from None
    if store.backend_name() != "sql":
        raise SystemExit(
            "Integration needed: the worker resolved its store to "
            f"{store.backend_name()!r}, not the shared PostgreSQL database. "
            "Set DATABASE_URL (or OCCDESK_WORKER_STORE=sql) - refusing to call a "
            "JSON file on a container's own disk the M1 stack."
        )
    from services.common.logging import configure

    configure("worker", "INFO")
    heartbeat = Path("/tmp/occdesk-worker-heartbeat")
    while True:
        heartbeat.touch()
        worker.run(max_messages=1)
        heartbeat.touch()
        time.sleep(0.05)


if __name__ == "__main__":
    main()
