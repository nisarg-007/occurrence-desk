"""Apply the database owner's migrations and idempotent local seeds."""

import subprocess
import sys
from pathlib import Path


def main():
    if not Path("db/alembic.ini").is_file():
        raise SystemExit("Missing Parva's database code. Integrate the parva branch first.")
    for arguments in [
        ["-m", "alembic", "-c", "db/alembic.ini", "upgrade", "head"],
        ["-m", "db.seed.hazard_categories"],
        ["-m", "db.seed.users"],
    ]:
        subprocess.run([sys.executable, *arguments], check=True)


if __name__ == "__main__":
    main()
