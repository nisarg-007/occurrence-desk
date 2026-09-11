"""Cross-platform local commands. Uses only Python's standard library on the host."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".env.local"
SAMPLE = ROOT / "tests/e2e/fixtures/nmac.pdf"


def run(arguments, **kwargs):
    return subprocess.run(arguments, cwd=ROOT, check=True, **kwargs)


def init():
    if not ENV.exists():
        values = {
            "LOCAL_DB_PASSWORD": secrets.token_hex(24),
            "LOCAL_S3_USER": "occdesk-local",
            "LOCAL_S3_PASSWORD": secrets.token_hex(24),
            "LOCAL_JWT_SECRET": secrets.token_hex(32),
        }
        with ENV.open("x", encoding="utf-8") as handle:
            handle.write("# Generated local-only settings. Never commit this file.\n")
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
        if os.name != "nt":
            ENV.chmod(0o600)
    (ROOT / "data").mkdir(exist_ok=True)
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)


def docker():
    binary = shutil.which("docker")
    if not binary and os.name == "nt":
        candidates = [Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")]
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(
                Path(local_app_data) / "Programs/DockerDesktop/resources/bin/docker.exe"
            )
        binary = next((str(path) for path in candidates if path.is_file()), None)
    if not binary:
        raise SystemExit(
            "Docker is missing. Install and start Docker Desktop with Linux containers."
        )
    return binary


def compose(*arguments):
    init()
    run(
        [
            docker(),
            "compose",
            "--env-file",
            str(ENV),
            "-f",
            str(ROOT / "docker-compose.yml"),
            *arguments,
        ]
    )


def source_blockers(root=ROOT):
    required = {
        "db/alembic.ini": "Parva: database migrations have not been integrated",
        "db/models.py": "Parva: database models have not been integrated",
        "services/worker/worker.py": "Smit: worker has not been integrated",
        "services/worker/store.py": "Smit: persistent worker store is missing",
    }
    return [message for path, message in required.items() if not (root / path).is_file()]


def require_sources():
    errors = source_blockers()
    if errors:
        raise SystemExit(
            "Application prerequisites are incomplete:\n- "
            + "\n- ".join(errors)
            + "\nUse infra-up to test Wasim's infrastructure separately."
        )


def fetch_sample():
    init()
    if SAMPLE.exists():
        print("Using existing sample; remove it explicitly to download a newer copy.")
        return
    url = "https://asrs.arc.nasa.gov/docs/rpsts/nmac.pdf"
    request = urllib.request.Request(url, headers={"User-Agent": "OccurrenceDesk-course-demo/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        blob = response.read(26_214_401)
    if not blob.startswith(b"%PDF-") or len(blob) > 26_214_400:
        raise SystemExit("Download was not a PDF within the 25 MiB upload limit.")
    SAMPLE.write_bytes(blob)
    SAMPLE.with_suffix(".source.json").write_text(
        json.dumps(
            {
                "source": url,
                "sha256": hashlib.sha256(blob).hexdigest(),
                "bytes": len(blob),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Downloaded NASA sample with a SHA-256 provenance file (both ignored by git).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "init",
            "doctor",
            "config",
            "infra-up",
            "up",
            "down",
            "destroy",
            "status",
            "logs",
            "db-reset",
            "db-load",
            "test",
            "e2e",
            "fmt",
            "sample",
            "build",
            "infra-test",
        ],
    )
    parser.add_argument("--yes", action="store_true", help="Confirm destructive reset")
    parser.add_argument("--file", help="BTS CSV inside the project data directory")
    args = parser.parse_args()
    if args.action == "init":
        init()
        print("Local configuration ready; existing credentials preserved.")
    elif args.action == "doctor":
        errors = source_blockers()
        for error in errors:
            print("PENDING:", error)
        run([docker(), "version"])
        run([docker(), "compose", "version"])
        if errors:
            raise SystemExit(1)
    elif args.action == "config":
        compose("config", "--quiet")  # Never print resolved secrets.
    elif args.action == "infra-up":
        compose("up", "-d", "--build", "db", "minio", "elasticmq")
        compose("run", "--rm", "bootstrap")
        print("Local infrastructure ready; application integration is a separate check.")
    elif args.action == "up":
        require_sources()
        compose("--profile", "app", "up", "-d", "--build", "--wait", "--wait-timeout", "180")
    elif args.action == "down":
        compose("--profile", "app", "down")
        print("Stopped. Database, objects and queue volumes retained.")
    elif args.action == "destroy":
        if not args.yes:
            raise SystemExit("This deletes this project's local volumes. Re-run destroy --yes.")
        compose("--profile", "app", "--profile", "tools", "down", "--volumes")
    elif args.action == "status":
        compose("--profile", "app", "ps", "--all")
    elif args.action == "logs":
        compose("--profile", "app", "logs", "--tail", "100")
    elif args.action == "db-reset":
        require_sources()
        if not args.yes:
            raise SystemExit("This erases local DB rows. Re-run db-reset --yes.")
        compose("--profile", "app", "stop", "api", "worker")
        compose(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "occdesk",
            "-d",
            "occdesk",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        )
        compose("run", "--rm", "migrate")
        print("Database reset. Run up to restart API and worker. Object/queue data is retained.")
    elif args.action == "db-load":
        require_sources()
        if not args.file:
            raise SystemExit("Provide --file data/<December-2022-BTS-file>.csv")
        path = (ROOT / args.file).resolve()
        data_root = (ROOT / "data").resolve()
        if not path.is_relative_to(data_root) or not path.is_file():
            raise SystemExit("The BTS file must exist inside this project's data/ directory.")
        target = "/data/" + path.relative_to(data_root).as_posix()
        compose("run", "--rm", "--no-deps", "tools", "python", "-m", "db.seed.load_bts", target)
    elif args.action == "test":
        compose(
            "run",
            "--build",
            "--rm",
            "--no-deps",
            "-e",
            "SQS_QUEUE_URL=",
            "tools",
            "python",
            "-m",
            "pytest",
            "tests/unit",
            "tests/contract",
            "infra/tests",
            "-q",
        )
    elif args.action == "infra-test":
        compose("run", "--rm", "bootstrap")
        compose("run", "--rm", "--no-deps", "tools", "python", "-m", "infra.local.smoke")
    elif args.action == "e2e":
        require_sources()
        if not SAMPLE.is_file():
            raise SystemExit(
                "Sample missing: run sample first. Refusing silently skipped E2E tests."
            )
        if not os.environ.get("E2E_PASSWORD"):
            raise SystemExit(
                "Set E2E_PASSWORD to the local fixture user password before running e2e."
            )
        environment = dict(os.environ, E2E_BASE_URL="http://localhost:8000")
        run([sys.executable, "-m", "pytest", "tests/e2e", "-q", "-ra"], env=environment)
    elif args.action == "fmt":
        run([sys.executable, "-m", "ruff", "format", "infra"])
        run([sys.executable, "-m", "ruff", "check", "--fix", "infra"])
    elif args.action == "sample":
        fetch_sample()
    elif args.action == "build":
        compose("--profile", "app", "--profile", "tools", "build")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
