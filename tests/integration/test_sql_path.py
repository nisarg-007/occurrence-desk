"""End-to-end over the real tables: PDF -> parser -> Postgres -> repository.

Skipped unless `OCCDESK_TEST_DATABASE_URL` points at a live PostgreSQL 16 with
the migrations applied and the seeds run:

    export OCCDESK_TEST_DATABASE_URL=postgresql+psycopg://occdesk:occdesk@localhost:5432/occdesk
    alembic -c db/alembic.ini upgrade head
    python -m db.seed.hazard_categories && python -m db.seed.users
    pytest tests/integration -v

A separate variable from `DATABASE_URL` on purpose: this test truncates
documents and reports, and it must be impossible to point it at a database
someone is using by having their shell already configured.

It asserts the guarantees in the success criteria that only a real database can
demonstrate - the two unique constraints collapsing a duplicate, and the claim
predicate refusing an already-parsed document - plus the seam that the merge
broke: the score the API shows matching the score `/why` explains.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("OCCDESK_TEST_DATABASE_URL"),
    reason="needs a live PostgreSQL: set OCCDESK_TEST_DATABASE_URL",
)

FIXTURE_SHA = "a1" * 32


@pytest.fixture(scope="module")
def live_db():
    """Point every module that reads settings at the test database, once."""
    os.environ["DATABASE_URL"] = os.environ["OCCDESK_TEST_DATABASE_URL"]
    os.environ["OCCDESK_WORKER_STORE"] = "sql"
    os.environ.setdefault("APP_ENV", "local")
    from services.common.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def fixture_pdf(tmp_path_factory):
    from tests.integration.make_fixture_pdf import build

    return build(str(tmp_path_factory.mktemp("pdf") / "fixture.pdf"))


@pytest.fixture
def clean_worker_state(live_db):
    from services.worker import store

    store.reset()
    yield store
    store.reset()


def _parse(path: str, document_id: int) -> list[dict]:
    from services.worker.hazards import predict_hazards
    from services.worker.parser import parse_pdf

    records = parse_pdf(path, document_id=document_id)
    for record in records:
        record["hazards"].extend(predict_hazards(record["narrative"]))
    return records


def test_parsed_records_land_in_the_real_tables(clean_worker_state, fixture_pdf):
    store = clean_worker_state
    store.register_document(1, sha256=FIXTURE_SHA, s3_bucket="b", s3_key="raw/f.pdf")

    assert store.claim_for_parsing(1) is True
    inserted = store.save_reports(1, _parse(fixture_pdf, 1))
    store.mark_parsed(1)

    assert inserted == 2
    assert store.report_count() == 2
    assert store.document_status(1)["status"] == "parsed"

    from sqlalchemy import func, select

    from db import models
    from db.database import session_scope

    with session_scope() as session:
        # the coded tree, the flattened pairs and NASA's own hazard rows all landed
        report = session.scalar(select(models.Report).where(models.Report.acn == "9000001"))
        assert report.coded["Assessments"]["Primary Problem"] == "Human Factors"
        assert report.narrative
        assert (
            session.scalar(
                select(func.count())
                .select_from(models.ReportField)
                .where(models.ReportField.report_id == report.id)
            )
            > 0
        )
        sources = set(
            session.scalars(
                select(models.ReportHazard.source).where(models.ReportHazard.report_id == report.id)
            )
        )
        assert sources == {"nasa"}, (
            "NASA's codes are the ground truth and must be stored as source='nasa'; "
            f"got {sources}"
        )


def test_the_same_document_parsed_twice_produces_one_set_of_reports(
    clean_worker_state, fixture_pdf
):
    """The success criterion, on the real constraints rather than a stand-in."""
    store = clean_worker_state
    store.register_document(1, sha256=FIXTURE_SHA, s3_bucket="b", s3_key="raw/f.pdf")
    store.claim_for_parsing(1)
    records = _parse(fixture_pdf, 1)

    assert store.save_reports(1, records) == 2
    assert store.save_reports(1, records) == 0  # redelivered message
    assert store.report_count() == 2

    store.mark_parsed(1)
    assert store.claim_for_parsing(1) is False  # duplicate is dropped, not reparsed


def test_a_failed_document_is_still_reclaimable(clean_worker_state, fixture_pdf):
    """'failed' must stay retryable or a message that failed once gets deleted as a
    duplicate instead of reaching the DLQ after maxReceiveCount."""
    store = clean_worker_state
    store.register_document(2, sha256="b2" * 32, s3_bucket="b", s3_key="raw/b.pdf")

    assert store.claim_for_parsing(2) is True
    store.mark_failed(2, "RuntimeError: deliberately broken")
    assert store.claim_for_parsing(2) is True
    assert store.document_status(2)["attempts"] == 2


def test_the_score_the_worklist_shows_is_the_score_why_explains(clean_worker_state, fixture_pdf):
    """The bug the merge produced: SqlRepo had no priority(), a router masked it with
    hasattr, and the worklist read 0 while /why read 41 for the same report."""
    import datetime as dt

    from db.database import get_sessionmaker
    from db.repo import SqlRepo
    from services.api import ranking

    store = clean_worker_state
    store.register_document(1, sha256=FIXTURE_SHA, s3_bucket="b", s3_key="raw/f.pdf")
    store.claim_for_parsing(1)
    store.save_reports(1, _parse(fixture_pdf, 1))
    store.mark_parsed(1)

    repo = SqlRepo(get_sessionmaker())
    rows = repo.list_reports(cursor=None, page_size=10)
    assert rows, "the worklist must see the rows the worker just wrote"

    today = dt.date.today()
    for row in rows:
        listed = repo.priority(row, today)
        explained = ranking.explain(
            ranking.ScoreInput(
                severity_weights=row.severity_weights,
                best_link_confidence=row.best_link_confidence,
                report_date=row.report_date,
                manager_flagged=row.manager_flagged,
            ),
            today,
        )
        assert (
            listed == explained["priority"]
        ), f"report {row.acn}: worklist says {listed}, /why says {explained['priority']}"
        assert listed > 0, "a report with a hazard row cannot score zero"


def test_throughput_counter_sees_what_the_worker_parsed(clean_worker_state, fixture_pdf):
    """GET /queue/stats' throughput_per_min, and so the drain-time estimate, is this
    count. It read 0 forever because nothing wrote the event it counts."""
    from db.database import get_sessionmaker
    from db.repo import SqlRepo

    store = clean_worker_state
    store.register_document(1, sha256=FIXTURE_SHA, s3_bucket="b", s3_key="raw/f.pdf")
    store.claim_for_parsing(1)
    store.save_reports(1, _parse(fixture_pdf, 1))
    store.mark_parsed(1)

    assert SqlRepo(get_sessionmaker()).parsed_in_last_60s() == 1
