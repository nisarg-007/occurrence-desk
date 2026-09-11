"""SQLAlchemy 2.0 models — the single source of truth for the schema.

This mirrors work-pack section 0.6 verbatim on table/column names, with one deliberate
addition: `reports.priority`. The ranking formula (`services/api/ranking.py`) depends on
`today`, so it cannot be a Postgres `GENERATED ALWAYS AS` column — `age_days` is not
immutable. Instead it's a plain nullable column, refreshed by `db.priority.refresh_priorities`
(called after any write that can change a report's score, and safe to also run on a
schedule so recency drifts stay bounded). Nisarg's keyset pagination
(`services/api/pagination.py`) is written against exactly this column and the composite
index below — that's the conversation the work pack asks for, already had.

Two unique constraints carry the whole idempotency story: `documents.sha256` (the same PDF
submitted twice is one row) and `reports.acn` (the same ASRS record extracted twice is one
row).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

#: `ingest_events.event` values. Two lanes write and read these strings - the worker
#: writes them, `SqlRepo.parsed_in_last_60s` counts them - so they live in one place.
#: They were inline literals in both files and did not match, which made the API's
#: throughput_per_min read 0 no matter how much the worker parsed.
EVENT_DOCUMENT_PARSED = "document.parsed"
EVENT_REPORT_EXTRACTED = "report.extracted"


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Reference (BTS)
# ---------------------------------------------------------------------------


class Carrier(Base):
    __tablename__ = "carriers"

    #: BTS's own carrier code - a natural key, always supplied explicitly. Not a surrogate,
    #: so no autoincrement sequence.
    dot_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    iata_code: Mapped[str | None] = mapped_column(String(4))
    name: Mapped[str | None] = mapped_column(String(200))

    flights: Mapped[list[Flight]] = relationship(back_populates="carrier")


class Airport(Base):
    __tablename__ = "airports"

    #: BTS's own airport id - a natural key, always supplied explicitly. Not a surrogate.
    airport_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    iata_code: Mapped[str | None] = mapped_column(String(3), index=True)
    city_name: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(2))
    wac: Mapped[int | None]


class Aircraft(Base):
    __tablename__ = "aircraft"

    tail_number: Mapped[str] = mapped_column(String(10), primary_key=True)
    first_seen: Mapped[dt.date | None] = mapped_column(Date)
    last_seen: Mapped[dt.date | None] = mapped_column(Date)


# ---------------------------------------------------------------------------
# Operational spine (BTS On-Time Performance)
# ---------------------------------------------------------------------------


class Flight(Base):
    __tablename__ = "flights"
    __table_args__ = (
        UniqueConstraint("flight_date", "reporting_airline", "flight_number", "origin_airport_id"),
        Index("ix_flights_date_origin", "flight_date", "origin_airport_id"),  # linkage
        CheckConstraint(
            "cancellation_code IS NULL OR cancellation_code IN ('A','B','C','D')",
            name="ck_flights_cancellation_code",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    flight_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reporting_airline: Mapped[str] = mapped_column(String(4), nullable=False)
    dot_id: Mapped[int] = mapped_column(ForeignKey("carriers.dot_id"), nullable=False)
    flight_number: Mapped[int] = mapped_column(nullable=False)
    tail_number: Mapped[str | None] = mapped_column(ForeignKey("aircraft.tail_number"))
    origin_airport_id: Mapped[int] = mapped_column(
        ForeignKey("airports.airport_id"), nullable=False
    )
    dest_airport_id: Mapped[int] = mapped_column(ForeignKey("airports.airport_id"), nullable=False)

    # HH:MM local, or NULL. BTS's `2400` is stored as `23:59:59.999999`-adjacent midnight
    # rollover is NOT modelled here: it is normalised to `00:00` on the *next* civil day by
    # the loader (see `db/seed/load_bts.py::_parse_hhmm`), and the decision is written down
    # there rather than guessed at read time.
    crs_dep_time: Mapped[dt.time | None] = mapped_column(Time)
    dep_time: Mapped[dt.time | None] = mapped_column(Time)
    dep_delay_minutes: Mapped[int | None]

    crs_arr_time: Mapped[dt.time | None] = mapped_column(Time)
    arr_time: Mapped[dt.time | None] = mapped_column(Time)
    arr_delay_minutes: Mapped[int | None]

    cancelled: Mapped[bool] = mapped_column(default=False, nullable=False)
    cancellation_code: Mapped[str | None] = mapped_column(String(1))
    diverted: Mapped[bool] = mapped_column(default=False, nullable=False)

    carrier_delay: Mapped[int | None]
    weather_delay: Mapped[int | None]
    nas_delay: Mapped[int | None]
    security_delay: Mapped[int | None]
    late_aircraft_delay: Mapped[int | None]

    distance: Mapped[int | None]

    carrier: Mapped[Carrier] = relationship(back_populates="flights")
    origin: Mapped[Airport] = relationship(foreign_keys=[origin_airport_id])
    dest: Mapped[Airport] = relationship(foreign_keys=[dest_airport_id])
    report_links: Mapped[list[ReportFlightLink]] = relationship(back_populates="flight")


# ---------------------------------------------------------------------------
# Documents and reports
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('analyst','manager','admin')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received','queued','parsing','parsed','failed')",
            name="ck_documents_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: The idempotency key. The same PDF submitted twice is one row - `create_document`
    #: in `db/repo.py` is written as "insert, or return the existing row on conflict",
    #: never "insert, then check".
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    s3_bucket: Mapped[str] = mapped_column(String(200), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    byte_size: Mapped[int | None]
    page_count: Mapped[int | None]
    #: NOT NULL, unlike the raw §0.6 DDL sketch: every upload goes through the analyst-only
    #: `POST /documents/upload-url`, so there is no code path that creates a document without
    #: an uploader - `services/api/repo.py::DocumentRow.uploaded_by` is typed `int`, not
    #: `int | None`, on exactly that assumption.
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    error_text: Mapped[str | None]

    reports: Mapped[list[Report]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class HazardCategory(Base):
    __tablename__ = "hazard_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Data, not a magic number in code - Nisarg's `ranking.py` reads this to score
    #: severity. A change to a weight is a dated row update, not a migration.
    severity_weight: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)

    report_hazards: Mapped[list[ReportHazard]] = relationship(back_populates="category")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        # Keyset pagination on exactly this tuple - see services/api/pagination.py.
        Index(
            "ix_reports_priority_keyset",
            "priority",
            "report_date",
            "id",
        ),
        Index("ix_reports_narrative_tsv", "narrative_tsv", postgresql_using="gin"),
        Index(
            "ix_reports_coded",
            "coded",
            postgresql_using="gin",
            postgresql_ops={"coded": "jsonb_path_ops"},
        ),
        CheckConstraint("state IN ('new','triaged','escalated','closed')", name="ck_reports_state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    #: The second idempotency key. The same ASRS record extracted twice is one row.
    acn: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    page_from: Mapped[int | None]
    page_to: Mapped[int | None]
    report_date: Mapped[dt.date | None] = mapped_column(Date)
    local_time_of_day: Mapped[str | None] = mapped_column(String(20))
    synopsis: Mapped[str | None]
    narrative: Mapped[str] = mapped_column(nullable=False)
    #: `to_tsvector('english', narrative)`, STORED - a real Postgres GENERATED column, not
    #: maintained by the application. `coalesce` so a (theoretically impossible, NOT NULL)
    #: missing narrative can't break the expression.
    narrative_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(narrative, ''))", persisted=True),
        nullable=True,
    )
    #: Full NASA field tree, verbatim labels as keys. See contracts/extraction-record.schema.json.
    coded: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    #: Denormalised score, refreshed by `db.priority.refresh_priorities` - see module
    #: docstring for why this can't be a Postgres GENERATED column.
    priority: Mapped[int | None]
    state: Mapped[str] = mapped_column(String(20), default="new", nullable=False)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    manager_flagged: Mapped[bool] = mapped_column(default=False, nullable=False)

    document: Mapped[Document] = relationship(back_populates="reports")
    fields: Mapped[list[ReportField]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    hazards: Mapped[list[ReportHazard]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    flight_links: Mapped[list[ReportFlightLink]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    dispositions: Mapped[list[Disposition]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class ReportField(Base):
    """Flattened (path, value) pairs, e.g. ('Assessments.Primary Problem', 'Human Factors').

    Verbatim NASA dotted paths - not snake-cased, not tidied - so a human holding the PDF
    can check the extraction line by line (Smit's Task A accuracy is measured against this).
    """

    __tablename__ = "report_fields"

    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[str] = mapped_column(String(2000), primary_key=True)

    report: Mapped[Report] = relationship(back_populates="fields")


class ReportHazard(Base):
    """`source='nasa'` rows are ground truth (NASA's own `Anomaly.*` codes); `source='model'`
    rows are Smit's classifier's prediction. Keeping both in one table is what makes scoring
    the categorisation task a single query instead of a join across two systems."""

    __tablename__ = "report_hazards"
    __table_args__ = (
        CheckConstraint("source IN ('nasa','model')", name="ck_report_hazards_source"),
        Index("ix_report_hazards_category", "category_id", "report_id"),
    )

    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("hazard_categories.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(10), primary_key=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)

    report: Mapped[Report] = relationship(back_populates="hazards")
    category: Mapped[HazardCategory] = relationship(back_populates="report_hazards")


class ReportFlightLink(Base):
    """The probabilistic join between a de-identified ASRS report and a real BTS flight.
    See `db/repo.py::candidate_flights` for the scored candidate query."""

    __tablename__ = "report_flight_links"

    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True
    )
    flight_id: Mapped[int] = mapped_column(ForeignKey("flights.id"), primary_key=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    method: Mapped[str] = mapped_column(String(60), nullable=False)

    report: Mapped[Report] = relationship(back_populates="flight_links")
    flight: Mapped[Flight] = relationship(back_populates="report_links")


# ---------------------------------------------------------------------------
# Analyst workflow
# ---------------------------------------------------------------------------


class Disposition(Base):
    __tablename__ = "dispositions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('new','triaged','escalated','closed')",
            name="ck_dispositions_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    analyst_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int | None]
    note: Mapped[str | None] = mapped_column(String(4000))
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), nullable=False)

    report: Mapped[Report] = relationship(back_populates="dispositions")


class IngestEvent(Base):
    """Append-only breadcrumb trail per document - `trace_id` carried in `detail` ties a
    row here to the same-named field in every worker/API log line for one document's life."""

    __tablename__ = "ingest_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    event: Mapped[str] = mapped_column(String(60), nullable=False)
    at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)


class LinkageWeight(Base):
    """Weights for `db/linkage.py`'s scored flight-candidate query - data, not a constant in
    the SQL, so a re-weighting is a dated row UPDATE (same reasoning as
    `hazard_categories.severity_weight`)."""

    __tablename__ = "linkage_weights"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), nullable=False)
