"""
The worker's real storage: Parva's Postgres tables, via her SQLAlchemy models.

This replaces the JSON stand-in (`json_store.py`) that the worker lane used
while `db/models.py` did not exist. The function surface is identical, so
`worker.py`'s control flow does not change - which was the point of writing
the stand-in behind a function boundary in the first place.

Where each piece of an extracted record lands (work-pack §3.4):

    coded tree, verbatim            -> reports.coded            (jsonb)
    flattened (path, value) pairs   -> report_fields
    narrative / synopsis            -> reports.narrative / .synopsis
    NASA Anomaly.* codes            -> report_hazards, source='nasa'
    our classifier's codes          -> report_hazards, source='model'

Two constraints carry the idempotency story and both are enforced by the
database, not by application logic:

    documents.sha256 UNIQUE   - the same PDF submitted twice is one row
    reports.acn      UNIQUE   - the same ASRS record extracted twice is one row

`save_reports` inserts with ON CONFLICT (acn) DO NOTHING and returns how many
rows were actually new, so a redelivered message contributes 0 the second
time. That is the assertion Sowmya's replay checks under load.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from db import models
from db.database import session_scope
from db.priority import refresh_priorities

logger = logging.getLogger("worker.store")

#: Hazard codes the worker emits that are not in `hazard_categories` get folded
#: into this category rather than silently dropped, so a ground-truth row is
#: never lost just because the taxonomy seed predates a new report set.
FALLBACK_HAZARD_CODE = "other"


def reset() -> None:
    """Wipe document/report state. Test and demo scripts only.

    Deliberately does not touch `users`, `hazard_categories`, `linkage_weights`
    or the BTS spine - those are seeds, not worker output.
    """
    with session_scope() as session:
        session.execute(models.Report.__table__.delete())
        session.execute(models.IngestEvent.__table__.delete())
        session.execute(models.Document.__table__.delete())


def _fixture_uploader_id(session) -> int:
    """`documents.uploaded_by` is NOT NULL. Harnesses that stand in for the API
    have no real principal, so attribute to the seeded analyst."""
    user_id = session.scalar(select(models.User.id).order_by(models.User.id).limit(1))
    if user_id is None:
        raise RuntimeError(
            "no users in the database - run `python -m db.seed.users` before registering "
            "documents from a harness (documents.uploaded_by is NOT NULL)"
        )
    return user_id


def register_document(document_id: int, sha256: str, s3_bucket: str, s3_key: str) -> None:
    """Equivalent of the INSERT that POST /documents/{id}/complete would already
    have done. Harness-only: the real API owns this write path."""
    with session_scope() as session:
        stmt = (
            insert(models.Document)
            .values(
                id=document_id,
                sha256=sha256,
                s3_bucket=s3_bucket,
                s3_key=s3_key,
                uploaded_by=_fixture_uploader_id(session),
                status="queued",
                attempts=0,
            )
            .on_conflict_do_nothing(index_elements=["sha256"])
        )
        session.execute(stmt)


def claim_for_parsing(document_id: int) -> bool:
    """True only for the call that actually gets to parse this document.

    'queued' / 'parsing' / 'failed' are all reclaimable - a previous attempt
    that crashed mid-parse or genuinely failed should still be retried by a
    redelivered message. Only 'parsed' is refused: that is the real duplicate
    case. The work-pack's own pseudocode says `status IN ('queued','parsing')`,
    which silently excludes 'failed' and deletes a retryable message as a
    duplicate - a bug the worker lane found by running the poison-PDF case,
    and the reason this predicate is `<> 'parsed'` instead.
    """
    with session_scope() as session:
        claimed = session.execute(
            update(models.Document)
            .where(models.Document.id == document_id, models.Document.status != "parsed")
            .values(status="parsing", attempts=models.Document.attempts + 1)
            .returning(models.Document.id)
        ).scalar_one_or_none()
        return claimed is not None


def mark_parsed(document_id: int) -> None:
    with session_scope() as session:
        session.execute(
            update(models.Document)
            .where(models.Document.id == document_id)
            .values(status="parsed", error_text=None)
        )


def mark_failed(document_id: int, error_text: str) -> None:
    with session_scope() as session:
        session.execute(
            update(models.Document)
            .where(models.Document.id == document_id)
            .values(status="failed", error_text=error_text)
        )


def document_status(document_id: int) -> dict | None:
    with session_scope() as session:
        doc = session.get(models.Document, document_id)
        if doc is None:
            return None
        return {
            "id": doc.id,
            "sha256": doc.sha256,
            "s3_bucket": doc.s3_bucket,
            "s3_key": doc.s3_key,
            "status": doc.status,
            "attempts": doc.attempts,
            "error_text": doc.error_text,
        }


def _hazard_category_ids(session) -> dict[str, int]:
    return dict(session.execute(select(models.HazardCategory.code, models.HazardCategory.id)).all())


def _write_hazards(session, report_id: int, hazards: list[dict], categories: dict[str, int]) -> None:
    """One row per (report, category, source). Highest confidence wins when the
    same category arrives twice from the same source - which happens whenever
    two distinct NASA axes fold into `other`."""
    best: dict[tuple[int, str], float] = {}
    for hazard in hazards:
        code = hazard["code"]
        category_id = categories.get(code) or categories.get(FALLBACK_HAZARD_CODE)
        if category_id is None:
            logger.warning(
                "dropping hazard with no category row and no '%s' fallback: %s",
                FALLBACK_HAZARD_CODE,
                code,
            )
            continue
        if code not in categories:
            logger.info("hazard code %r not in taxonomy - folded into %r", code, FALLBACK_HAZARD_CODE)
        key = (category_id, hazard["source"])
        best[key] = max(best.get(key, 0.0), float(hazard["confidence"]))

    for (category_id, source), confidence in best.items():
        session.execute(
            insert(models.ReportHazard)
            .values(
                report_id=report_id,
                category_id=category_id,
                source=source,
                confidence=confidence,
            )
            .on_conflict_do_nothing(index_elements=["report_id", "category_id", "source"])
        )


def save_reports(document_id: int, extracted_records: list[dict]) -> int:
    """INSERT ... ON CONFLICT (acn) DO NOTHING, plus the child rows.

    Returns how many records were actually NEW - the same document parsed twice
    contributes 0 the second time, which is the idempotency guarantee in the
    success criteria.
    """
    if not extracted_records:
        return 0

    inserted_ids: list[int] = []
    with session_scope() as session:
        categories = _hazard_category_ids(session)
        for record in extracted_records:
            report_id = session.execute(
                insert(models.Report)
                .values(
                    document_id=document_id,
                    acn=record["acn"],
                    page_from=record.get("page_from"),
                    page_to=record.get("page_to"),
                    report_date=record.get("report_date"),
                    local_time_of_day=record.get("local_time_of_day"),
                    synopsis=record.get("synopsis"),
                    narrative=record["narrative"],
                    coded=record.get("coded") or {},
                )
                .on_conflict_do_nothing(index_elements=["acn"])
                .returning(models.Report.id)
            ).scalar_one_or_none()

            if report_id is None:
                continue  # this ACN already exists: the duplicate case, by design

            for field in record.get("fields") or []:
                session.execute(
                    insert(models.ReportField)
                    .values(report_id=report_id, path=field["path"], value=field["value"])
                    .on_conflict_do_nothing(index_elements=["report_id", "path", "value"])
                )

            _write_hazards(session, report_id, record.get("hazards") or [], categories)
            session.execute(
                insert(models.IngestEvent).values(
                    document_id=document_id,
                    event="report.extracted",
                    detail={"acn": record["acn"], "report_id": report_id},
                )
            )
            inserted_ids.append(report_id)

    # reports.priority is denormalised (see db/priority.py) and the hazard rows
    # that feed it only exist now - so score the new rows after they are
    # committed. This closes one of the two gaps db/README.md named as open.
    for report_id in inserted_ids:
        with session_scope() as session:
            refresh_priorities(session, report_id=report_id)

    return len(inserted_ids)


def report_count() -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(models.Report)) or 0)
