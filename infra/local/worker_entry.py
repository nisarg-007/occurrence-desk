"""Launch the worker with main-loop liveness and visible integration errors."""

import inspect
import time
from pathlib import Path


def main():
    try:
        from services.worker import store, worker
    except ModuleNotFoundError as exc:
        raise SystemExit(f"Missing worker implementation or dependency: {exc.name}") from None
    if "worker_state.json" in inspect.getsource(store):
        raise SystemExit(
            "Integration needed: Smit must replace JSON worker storage with the "
            "shared PostgreSQL database before the M1 stack can run."
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
