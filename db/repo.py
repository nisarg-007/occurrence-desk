"""`SqlRepo` — the real database behind `services.api.deps.Repository`.

Implements the exact same `Protocol` as `services.api.repo.InMemoryRepo` (the M1 stub), so
wiring it in is the one-line change `deps.py` already anticipates:

    from db.database import get_sessionmaker
    from db.repo import SqlRepo
    set_repo(SqlRepo(get_sessionmaker()))

No route in `services/api/` changes. This module owns everything below that Protocol
boundary: sessions, SQL, and the translation from ORM rows into the same `UserRow` /
`DocumentRow` / `ReportRow` dataclasses the stub already returns, so callers on either side
of the swap can't tell the difference except that the numbers are real.

Two idempotency rules live here exactly once, matching `documents.sha256` and `reports.acn`:
`create_document` is "insert, or return the existing row on conflict", never "insert, then
check" — a duplicate submit under concurrent load must not race two inserts past a
uniqueness check that already passed for both.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from db import models
from db.priority import refresh_priorities
from services.api import ranking
from services.api.pagination import Cursor
from services.api.repo import DocumentRow, ReportRow, UserRow

_SENTINEL_MIN_DATE = dt.date(1, 1, 1)


def _to_user_row(u: models.User) -> UserRow:
    return UserRow(
        id=u.id,
        email=u.email,
        password_hash=u.password_hash,
        role=u.role,
        is_active=u.is_active,
    )


def _to_document_row(d: models.Document) -> DocumentRow:
    return DocumentRow(
        id=d.id,
        sha256=d.sha256,
        s3_bucket=d.s3_bucket,
        s3_key=d.s3_key,
        original_filename=d.original_filename,
        byte_size=d.byte_size,
        uploaded_by=d.uploaded_by,
        uploaded_at=d.uploaded_at,
        status=d.status,
        attempts=d.attempts,
        error_text=d.error_text,
        page_count=d.page_count,
    )


def _to_report_row(r: models.Report) -> ReportRow:
    severity_weights = tuple(float(h.category.severity_weight) for h in r.hazards)
    hazards = [
        {
            "code": h.category.code,
            "label": h.category.label,
            "confidence": float(h.confidence),
            "source": h.source,
        }
        for h in r.hazards
    ]
    best_link = max(r.flight_links, key=lambda link: link.confidence, default=None)
    linked_flight = None
    best_link_confidence = float(best_link.confidence) if best_link else None
    if best_link is not None:
        f = best_link.flight
        linked_flight = {
            "flight_id": f.id,
            "confidence": float(best_link.confidence),
            "method": best_link.method,
            "flight_date": f.flight_date,
            "carrier": f.carrier.name if f.carrier else None,
            "origin": f.origin.iata_code if f.origin else None,
            "dest": f.dest.iata_code if f.dest else None,
        }
    return ReportRow(
        id=r.id,
        document_id=r.document_id,
        acn=r.acn,
        report_date=r.report_date,
        synopsis=r.synopsis,
        narrative=r.narrative,
        coded=r.coded,
        severity_weights=severity_weights,
        hazards=hazards,
        best_link_confidence=best_link_confidence,
        linked_flight=linked_flight,
        manager_flagged=r.manager_flagged,
        state=r.state,
        assigned_to=r.assigned_to,
    )


class SqlRepo:
    """Backed by Postgres. `is_stub = False` — the console's "demo data" banner logic
    (work pack / README) reads this the same way it reads `InMemoryRepo.is_stub`."""

    is_stub = False

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- Repository --------------------------------------------------------
    def user_by_email(self, email: str) -> UserRow | None:
        with self._session_factory() as session:
            u = session.scalar(select(models.User).where(models.User.email == email.lower()))
            return _to_user_row(u) if u else None

    def document_by_sha(self, sha256: str) -> DocumentRow | None:
        with self._session_factory() as session:
            d = session.scalar(select(models.Document).where(models.Document.sha256 == sha256))
            return _to_document_row(d) if d else None

    def create_document(self, **kw) -> DocumentRow:
        """Insert, or return the existing row on conflict - one round trip, no race between
        a SELECT and the INSERT that follows it under concurrent duplicate submits."""
        with self._session_factory() as session:
            stmt = (
                pg_insert(models.Document)
                .values(uploaded_at=dt.datetime.now(dt.UTC), **kw)
                .on_conflict_do_nothing(index_elements=[models.Document.sha256])
                .returning(models.Document)
            )
            row = session.scalar(stmt)
            if row is None:
                # Conflict: another submit of the same bytes already won. Read it back.
                row = session.scalar(
                    select(models.Document).where(models.Document.sha256 == kw["sha256"])
                )
            session.commit()
            assert row is not None
            return _to_document_row(row)

    def document(self, document_id: int) -> DocumentRow | None:
        with self._session_factory() as session:
            d = session.get(models.Document, document_id)
            return _to_document_row(d) if d else None

    def mark_queued(self, document_id: int) -> bool:
        """True only when this call is the one that transitions 'received' -> 'queued' - a
        single UPDATE ... WHERE status = 'received' so a duplicate `complete` call can't
        race the same row into 'queued' twice."""
        with self._session_factory() as session:
            result = session.execute(
                update(models.Document)
                .where(
                    models.Document.id == document_id,
                    models.Document.status == "received",
                )
                .values(status="queued")
            )
            session.commit()
            return bool(result.rowcount)

    def unmark_queued(self, document_id: int) -> None:
        with self._session_factory() as session:
            session.execute(
                update(models.Document)
                .where(models.Document.id == document_id, models.Document.status == "queued")
                .values(status="received")
            )
            session.commit()

    def reports_for_document(self, document_id: int) -> list[ReportRow]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(models.Report).where(models.Report.document_id == document_id)
            )
            return [_to_report_row(r) for r in rows]

    def report(self, report_id: int) -> ReportRow | None:
        with self._session_factory() as session:
            r = session.get(models.Report, report_id)
            return _to_report_row(r) if r else None

    def list_reports(
        self,
        *,
        cursor: Cursor | None = None,
        page_size: int = 50,
        category: str | None = None,
        state: str | None = None,
        priority_min: int | None = None,
        q: str | None = None,
    ) -> list[ReportRow]:
        """Keyset paged on exactly the tuple `services/api/pagination.py` encodes:
        `(priority DESC, report_date DESC NULLS LAST, id DESC)`, backed by
        `ix_reports_priority_keyset` - never `OFFSET`."""
        with self._session_factory() as session:
            date_expr = func.coalesce(models.Report.report_date, _SENTINEL_MIN_DATE)
            priority_expr = func.coalesce(models.Report.priority, 0)

            stmt = select(models.Report)
            if category:
                stmt = stmt.where(
                    models.Report.hazards.any(
                        models.ReportHazard.category.has(models.HazardCategory.code == category)
                    )
                )
            if state:
                stmt = stmt.where(models.Report.state == state)
            if priority_min is not None:
                stmt = stmt.where(priority_expr >= priority_min)
            if q:
                needle = f"%{q}%"
                stmt = stmt.where(
                    models.Report.narrative.ilike(needle) | models.Report.synopsis.ilike(needle)
                )
            if cursor is not None:
                cursor_date = cursor.report_date or _SENTINEL_MIN_DATE
                stmt = stmt.where(
                    func.row(priority_expr, date_expr, models.Report.id)
                    < func.row(cursor.priority, cursor_date, cursor.report_id)
                )
            stmt = stmt.order_by(priority_expr.desc(), date_expr.desc(), models.Report.id.desc())
            stmt = stmt.limit(page_size + 1)  # one extra row tells the caller more exist

            rows = session.scalars(stmt).all()
            return [_to_report_row(r) for r in rows]

    def add_disposition(self, report_id: int, analyst_id: int, **kw) -> dict:
        with self._session_factory() as session:
            disposition = models.Disposition(report_id=report_id, analyst_id=analyst_id, **kw)
            session.add(disposition)
            if kw.get("state"):
                session.execute(
                    update(models.Report)
                    .where(models.Report.id == report_id)
                    .values(state=kw["state"])
                )
            session.commit()
            session.refresh(disposition)
            return {
                "id": disposition.id,
                "report_id": disposition.report_id,
                "analyst_id": disposition.analyst_id,
                "state": disposition.state,
                "priority": disposition.priority,
                "note": disposition.note,
                "created_at": disposition.created_at,
            }

    def assign(self, report_id: int, analyst_id: int, manager_flagged: bool) -> ReportRow | None:
        with self._session_factory() as session:
            r = session.get(models.Report, report_id)
            if r is None:
                return None
            r.assigned_to = analyst_id
            r.manager_flagged = manager_flagged
            session.flush()
            refresh_priorities(session, report_id=report_id)  # manager_flagged moved the score
            session.commit()
            session.refresh(r)
            return _to_report_row(r)

    def parsed_in_last_60s(self) -> int:
        """Documents whose status became 'parsed' in the last 60 seconds. Backed by
        `ingest_events`, which the worker writes a `document.parsed` row to (Smit's lane) -
        this repo only reads it."""
        with self._session_factory() as session:
            cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=60)
            count = session.scalar(
                select(func.count())
                .select_from(models.IngestEvent)
                .where(
                    models.IngestEvent.event == models.EVENT_DOCUMENT_PARSED,
                    models.IngestEvent.at >= cutoff,
                )
            )
            return count or 0

    def priority(self, r: ReportRow, today: dt.date | None = None) -> int:
        """The same score `InMemoryRepo.priority` returns, from the same function.

        Computed from `ranking.py` rather than read from `reports.priority`, on
        purpose: the column is a denormalised copy that `priority.py` refreshes
        on write, so recency has drifted by however long it is since the last
        refresh. Reading the column would make the worklist and `/why` disagree.
        The column stays for keyset ordering; this is the number shown.

        SqlRepo omitted this method entirely, and `_summary` masked it with
        `hasattr(repo, "priority") else 0` - so every report in the API's
        worklist read priority 0 while `/why` on the same report read 41.
        Found by querying the live API, not by a test: both repositories
        satisfied the Protocol, because the Protocol did not name the method.
        """
        return ranking.priority(
            ranking.ScoreInput(
                severity_weights=r.severity_weights,
                best_link_confidence=r.best_link_confidence,
                report_date=r.report_date,
                manager_flagged=r.manager_flagged,
            ),
            today or dt.date.today(),
        )
