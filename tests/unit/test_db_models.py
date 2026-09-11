"""No live Postgres in this test - `db/README.md` covers the real `alembic upgrade head` /
`downgrade` round-trip against a running instance. This is the fast, always-on check: the
models import cleanly, §0.6's two idempotency constraints exist, and the FK graph a caller
would trip over first (loading flights before carriers/airports) is really there."""

from __future__ import annotations

from typing import cast

from sqlalchemy import Table
from sqlalchemy.sql.schema import ColumnCollectionConstraint

from db.models import (
    Airport,
    Base,
    Carrier,
    Document,
    Flight,
    HazardCategory,
    Report,
    ReportHazard,
)

_TABLE_NAMES = {
    "carriers",
    "airports",
    "aircraft",
    "users",
    "documents",
    "hazard_categories",
    "flights",
    "reports",
    "report_fields",
    "report_hazards",
    "report_flight_links",
    "dispositions",
    "ingest_events",
    "linkage_weights",
}


def _table(model: type) -> Table:
    """`Mapped.__table__` is typed as the generic `FromClause` in SQLAlchemy's stubs, which
    doesn't declare `.constraints` / `.indexes` even though the runtime object is always a
    concrete `Table` for a mapped class. One cast here, instead of a `type: ignore` on every
    assertion below."""
    return cast(Table, model.__table__)  # type: ignore[attr-defined]


def _column_sets(table: Table) -> list[set[str]]:
    """Column-name sets of every constraint that actually has columns (unique/primary-key
    constraints do; a bare CHECK constraint doesn't)."""
    return [
        {c.name for c in uc.columns}
        for uc in table.constraints
        if isinstance(uc, ColumnCollectionConstraint)
    ]


def test_every_table_from_the_work_pack_exists() -> None:
    assert {t.name for t in Base.metadata.sorted_tables} == _TABLE_NAMES


def test_documents_sha256_is_unique() -> None:
    """The first idempotency key: the same PDF submitted twice is one row."""
    table = _table(Document)
    assert table.c.sha256.unique or {"sha256"} in _column_sets(table)


def test_reports_acn_is_unique() -> None:
    """The second idempotency key: the same ASRS record extracted twice is one row."""
    table = _table(Report)
    assert table.c.acn.unique or {"acn"} in _column_sets(table)


def test_flights_has_the_bts_natural_key() -> None:
    cols = {"flight_date", "reporting_airline", "flight_number", "origin_airport_id"}
    assert cols in _column_sets(_table(Flight))


def test_carriers_and_airports_are_not_surrogate_keyed() -> None:
    """BTS's own dot_id / airport_id, not an autoincrement sequence - loading a month twice
    (or loading carriers after flights by mistake) must fail on the real natural key, not
    silently mint duplicate rows under a fresh serial id."""
    assert _table(Carrier).c.dot_id.autoincrement is False
    assert _table(Airport).c.airport_id.autoincrement is False


def test_reports_priority_keyset_index_matches_pagination_tuple() -> None:
    """`services/api/pagination.py` pages on (priority DESC, report_date DESC, id DESC) -
    the composite index it explicitly asks Parva for must be exactly that tuple, in order."""
    index_cols = [
        [c.name for c in ix.columns]
        for ix in _table(Report).indexes
        if ix.name == "ix_reports_priority_keyset"
    ]
    assert index_cols == [["priority", "report_date", "id"]]


def test_report_hazards_distinguishes_ground_truth_from_model_predictions() -> None:
    """'nasa' rows are ground truth, 'model' rows are Smit's classifier - one table, one
    scoring query, per the work pack. The CHECK constraint is what stops a third value
    from ever being written."""
    check_sqltexts = [
        str(c.sqltext) for c in _table(ReportHazard).constraints if hasattr(c, "sqltext")
    ]
    assert any("'nasa'" in sql and "'model'" in sql for sql in check_sqltexts)


def test_hazard_category_severity_weight_is_the_only_place_the_number_lives() -> None:
    """Not a magic number in ranking.py - a column, so a re-weighting is a dated row UPDATE."""
    assert "severity_weight" in _table(HazardCategory).c
