"""Exact row counts for every table, to compare one database against another.

    python -m db.rowcounts                    # table counts, read from DATABASE_URL
    python -m db.rowcounts > counts-old.txt   # run on each database, then diff the two files

Read-only: it issues SELECT count(*) and nothing else. The password is never printed.
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from services.common.settings import get_settings


def row_counts(url: str) -> tuple[str | None, dict[str, int]]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            tables = sorted(inspect(connection).get_table_names())
            version = None
            if "alembic_version" in tables:
                version = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
            counts = {
                t: connection.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one()
                for t in tables
                if t != "alembic_version"
            }
        return version, counts
    finally:
        engine.dispose()


def main() -> None:
    url = get_settings().database_url
    version, counts = row_counts(url)
    print(f"alembic_version {version}")
    for table, count in counts.items():
        print(f"{table} {count}")
    print(f"TOTAL {sum(counts.values())}")


if __name__ == "__main__":
    main()
