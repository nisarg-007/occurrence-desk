"""Regression tests for the three bugs the lane merge produced.

All three were found by running the merged system against a live PostgreSQL and
a live API - not by any test - which is the reason they get tests now. Each one
passed review inside its own lane and only broke where two lanes meet.

These need no database on purpose: every one of them is a seam that can be
checked statically, and a test that needs Postgres would not run on a clean
clone, which is exactly how these got through the first time.
"""

from __future__ import annotations

import inspect
import re

from db import models, priority
from db import repo as sql_repo_module
from services.api.repo import InMemoryRepo, Repository


def test_both_repositories_implement_every_method_the_protocol_names():
    """`SqlRepo` shipped without `priority()`, and `_summary` masked the gap with
    `hasattr(repo, "priority") else 0` - so the worklist read priority 0 for every
    report while `/reports/{id}/why` read 41 for the same one. A Protocol that does
    not name a method the app calls cannot catch that, so assert both directions."""
    required = {
        name
        for name in vars(Repository)
        if not name.startswith("_") and callable(getattr(Repository, name, None))
    }
    assert "priority" in required, "the Protocol must name priority(): the routers call it"
    for implementation in (InMemoryRepo, sql_repo_module.SqlRepo):
        missing = sorted(name for name in required if not hasattr(implementation, name))
        assert not missing, f"{implementation.__name__} is missing {missing}"


def test_no_router_guards_a_repository_method_with_hasattr():
    """`hasattr(repo, ...) else <default>` turns a missing implementation into a
    plausible-looking wrong number instead of a crash. Nothing in the API may do it."""
    from services.api.routers import documents, reports

    for module in (documents, reports):
        source = inspect.getsource(module)
        assert "hasattr(repo" not in source, (
            f"{module.__name__} guards a repository call with hasattr - let it raise "
            "instead, or add the method to the Protocol"
        )


def test_single_report_priority_refresh_uses_the_updates_own_alias():
    """`refresh_priorities(report_id=...)` filtered on `r2.id`, but the UPDATE aliases
    `reports` as `r`, so every single-report refresh raised UndefinedTable. The module
    had only ever been compiled and logic-checked, never executed."""
    sql = priority._REFRESH_ALL_SQL.format(report_filter="AND r.id = :report_id")
    aliases = set(re.findall(r"\b([a-z][a-z0-9_]*)\.id\b", sql))
    known = {"r", "hc", "rh", "rfl"}
    assert aliases <= known, f"SQL references undeclared alias(es): {sorted(aliases - known)}"
    assert "r2." not in priority._REFRESH_ALL_SQL


def test_the_worker_writes_the_ingest_event_the_api_counts():
    """`SqlRepo.parsed_in_last_60s` is the `throughput_per_min` in GET /queue/stats and
    the denominator of the drain-time estimate. It counted `document.parsed` rows that
    nothing wrote, so throughput read 0 however much the worker parsed. Both sides now
    reference one constant - this test fails if either goes back to a literal."""
    from services.worker import sql_store

    written = inspect.getsource(sql_store.mark_parsed)
    counted = inspect.getsource(sql_repo_module.SqlRepo.parsed_in_last_60s)
    for side, source in (("worker write", written), ("API read", counted)):
        assert "EVENT_DOCUMENT_PARSED" in source, f"{side} does not use the shared constant"
        assert (
            f'"{models.EVENT_DOCUMENT_PARSED}"' not in source
        ), f"{side} hard-codes the event name again - use models.EVENT_DOCUMENT_PARSED"


def test_worker_store_refuses_an_unknown_backend_rather_than_defaulting():
    """A typo in OCCDESK_WORKER_STORE must not silently leave the worker writing to a
    JSON file on a container's own disk."""
    import pytest

    from services.worker import store

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OCCDESK_WORKER_STORE", "postgres")  # the plausible wrong spelling
        with pytest.raises(RuntimeError, match="OCCDESK_WORKER_STORE"):
            store.backend_name()

        mp.setenv("OCCDESK_WORKER_STORE", "sql")
        assert store.backend_name() == "sql"
        mp.setenv("OCCDESK_WORKER_STORE", "json")
        assert store.backend_name() == "json"


def test_worker_store_follows_database_url_when_not_told_otherwise():
    import pytest

    from services.worker import store

    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("OCCDESK_WORKER_STORE", raising=False)
        mp.setenv("DATABASE_URL", "postgresql+psycopg://occdesk:x@localhost:5432/occdesk")
        assert store.backend_name() == "sql"
        mp.delenv("DATABASE_URL", raising=False)
        assert store.backend_name() == "json"


def test_api_repo_choice_follows_the_same_rule_as_the_worker():
    """One variable configures both services. If these two rules drift, a deployment
    can run an API on Postgres and a worker on a JSON file, or the reverse."""
    from services.api import deps

    rule = inspect.getsource(deps._default_repo)
    assert "DATABASE_URL" in rule
    assert "OCCDESK_REPO" in rule
