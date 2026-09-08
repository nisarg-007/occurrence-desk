"""The storage seam.

Parva owns `db/models.py` and the migrations; they land in week 2. Until then the API is
developed and tested against `InMemoryRepo`, which implements the same Protocol. This is the
"generate a stub server from the contract and check it in" step from the work pack - everyone
else builds against a running API from week 1 instead of waiting on the schema.

When the SQLAlchemy models land, `SqlRepo` implements this Protocol and one line in deps.py
changes. No route changes.
"""

from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass, field
from typing import Protocol

from services.api import ranking
from services.api.pagination import Cursor, sort_key
from services.api.security import hash_password


@dataclass
class UserRow:
    id: int
    email: str
    password_hash: str
    role: str
    is_active: bool = True


@dataclass
class DocumentRow:
    id: int
    sha256: str
    s3_bucket: str
    s3_key: str
    original_filename: str | None
    byte_size: int | None
    uploaded_by: int
    uploaded_at: dt.datetime
    status: str = "received"
    attempts: int = 0
    error_text: str | None = None
    page_count: int | None = None


@dataclass
class ReportRow:
    id: int
    document_id: int
    acn: str
    report_date: dt.date | None
    synopsis: str | None
    narrative: str
    coded: dict = field(default_factory=dict)
    severity_weights: tuple[float, ...] = ()
    hazards: list[dict] = field(default_factory=list)
    best_link_confidence: float | None = None
    linked_flight: dict | None = None
    manager_flagged: bool = False
    state: str = "new"
    assigned_to: int | None = None


class Repository(Protocol):
    def user_by_email(self, email: str) -> UserRow | None: ...
    def document_by_sha(self, sha256: str) -> DocumentRow | None: ...
    def create_document(self, **kw) -> DocumentRow: ...
    def document(self, document_id: int) -> DocumentRow | None: ...
    def mark_queued(self, document_id: int) -> bool: ...
    def reports_for_document(self, document_id: int) -> list[ReportRow]: ...
    def report(self, report_id: int) -> ReportRow | None: ...
    def list_reports(
        self, *, cursor: Cursor | None, page_size: int, **filters
    ) -> list[ReportRow]: ...
    def add_disposition(self, report_id: int, analyst_id: int, **kw) -> dict: ...
    def assign(
        self, report_id: int, analyst_id: int, manager_flagged: bool
    ) -> ReportRow | None: ...
    def parsed_in_last_60s(self) -> int: ...


class InMemoryRepo:
    """M1 stub. Deliberately small and honest: it is not a database and does not pretend to be."""

    def __init__(self, seed: bool = True) -> None:
        self.users: dict[str, UserRow] = {}
        self.documents: dict[int, DocumentRow] = {}
        self.reports: dict[int, ReportRow] = {}
        self.dispositions: list[dict] = []
        # One counter per table, like BIGSERIAL - so a report id is not silently a user id.
        self._ids: dict[str, itertools.count] = {
            t: itertools.count(1) for t in ("users", "documents", "reports", "dispositions")
        }
        self._parsed_at: list[dt.datetime] = []
        if seed:
            self._seed()

    # -- helpers ---------------------------------------------------------------
    def _next(self, table: str) -> int:
        return next(self._ids[table])

    def _seed(self) -> None:
        # Local development logins only. The real seed script guards on ENV != 'prod'
        # in the script itself, not just in a comment.
        pw = hash_password("occdesk-local")
        for email, role in (
            ("analyst@occdesk.example", "analyst"),
            ("manager@occdesk.example", "manager"),
            ("admin@occdesk.example", "admin"),
        ):
            uid = self._next("users")
            self.users[email] = UserRow(uid, email, pw, role)

        today = dt.date.today()
        samples = [
            ("2068539", 6, "Conflict - NMAC", 0.95, 0.88, "conflict_nmac", "Conflict"),
            (
                "2071204",
                40,
                "Altitude deviation",
                0.60,
                0.42,
                "altitude_deviation",
                "Deviation - Altitude",
            ),
            (
                "2065118",
                200,
                "Runway incursion",
                0.90,
                0.10,
                "runway_incursion",
                "Ground Incursion",
            ),
            ("2059977", 700, "Bird strike", 0.35, 0.00, "bird_strike", "Aircraft Equipment"),
        ]
        doc_id = self._next("documents")
        self.documents[doc_id] = DocumentRow(
            id=doc_id,
            sha256="0" * 64,
            s3_bucket="occdesk-dev-docs",
            s3_key=f"raw/{today:%Y/%m/%d}/{'0' * 64}.pdf",
            original_filename="nmac.pdf",
            byte_size=1_843_200,
            uploaded_by=1,
            uploaded_at=dt.datetime.now(dt.UTC),
            status="parsed",
            page_count=112,
        )
        for acn, age, synopsis, sev, link, code, label in samples:
            rid = self._next("reports")
            self.reports[rid] = ReportRow(
                id=rid,
                document_id=doc_id,
                acn=acn,
                report_date=today - dt.timedelta(days=age),
                synopsis=synopsis,
                narrative=f"[stub narrative for ACN {acn} - real text arrives with Smit's parser]",
                severity_weights=(sev,),
                hazards=[{"code": code, "label": label, "confidence": 1.0, "source": "nasa"}],
                best_link_confidence=link,
            )

    def priority(self, r: ReportRow, today: dt.date | None = None) -> int:
        return ranking.priority(
            ranking.ScoreInput(
                severity_weights=r.severity_weights,
                best_link_confidence=r.best_link_confidence,
                report_date=r.report_date,
                manager_flagged=r.manager_flagged,
            ),
            today or dt.date.today(),
        )

    # -- Repository ------------------------------------------------------------
    def user_by_email(self, email: str) -> UserRow | None:
        return self.users.get(email.lower())

    def document_by_sha(self, sha256: str) -> DocumentRow | None:
        return next((d for d in self.documents.values() if d.sha256 == sha256), None)

    def create_document(self, **kw) -> DocumentRow:
        # Mirrors the `documents.sha256` unique constraint: the same PDF is one row.
        existing = self.document_by_sha(kw["sha256"])
        if existing:
            return existing
        did = self._next("documents")
        row = DocumentRow(id=did, uploaded_at=dt.datetime.now(dt.UTC), **kw)
        self.documents[did] = row
        return row

    def document(self, document_id: int) -> DocumentRow | None:
        return self.documents.get(document_id)

    def mark_queued(self, document_id: int) -> bool:
        """True when this call is the one that enqueued it. Second call returns False, still 202."""
        d = self.documents.get(document_id)
        if d is None or d.status != "received":
            return False
        d.status = "queued"
        return True

    def reports_for_document(self, document_id: int) -> list[ReportRow]:
        return [r for r in self.reports.values() if r.document_id == document_id]

    def report(self, report_id: int) -> ReportRow | None:
        return self.reports.get(report_id)

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
        today = dt.date.today()
        rows = list(self.reports.values())
        if category:
            rows = [r for r in rows if any(h["code"] == category for h in r.hazards)]
        if state:
            rows = [r for r in rows if r.state == state]
        if priority_min is not None:
            rows = [r for r in rows if self.priority(r, today) >= priority_min]
        if q:
            needle = q.lower()
            rows = [
                r
                for r in rows
                if needle in r.narrative.lower() or needle in (r.synopsis or "").lower()
            ]
        rows.sort(key=lambda r: sort_key(self.priority(r, today), r.report_date, r.id))
        if cursor is not None:
            anchor = sort_key(cursor.priority, cursor.report_date, cursor.report_id)
            rows = [
                r for r in rows if sort_key(self.priority(r, today), r.report_date, r.id) > anchor
            ]
        return rows[: page_size + 1]  # one extra row tells the caller whether more exist

    def add_disposition(self, report_id: int, analyst_id: int, **kw) -> dict:
        row = {
            "id": self._next("dispositions"),
            "report_id": report_id,
            "analyst_id": analyst_id,
            "created_at": dt.datetime.now(dt.UTC),
            **kw,
        }
        self.dispositions.append(row)
        r = self.reports.get(report_id)
        if r is not None and kw.get("state"):
            r.state = kw["state"]
        return row

    def assign(self, report_id: int, analyst_id: int, manager_flagged: bool) -> ReportRow | None:
        r = self.reports.get(report_id)
        if r is None:
            return None
        r.assigned_to = analyst_id
        r.manager_flagged = manager_flagged
        return r

    def parsed_in_last_60s(self) -> int:
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=60)
        self._parsed_at = [t for t in self._parsed_at if t >= cutoff]
        return len(self._parsed_at)
