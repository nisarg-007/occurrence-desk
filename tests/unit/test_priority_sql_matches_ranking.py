"""`db/priority.py` duplicates `services/api/ranking.py`'s formula in SQL so `reports.priority`
can be indexed and paged on directly (work pack §1.4 / §2.4). The weights and constants are
imported, not retyped, so they can't silently drift - but the *shape* of the SQL expression
(the GREATEST/COALESCE handling of an undated or future-dated report, in particular) is
independent code that could still disagree with `ranking.py` on an edge case. This test
re-derives the SQL's arithmetic in plain Python — mirroring exactly what
`db/priority.refresh_priorities`'s UPDATE computes per row — and checks it against
`ranking.priority()` for the cases the module docstring calls out.

No database needed: this is a logic cross-check, not an integration test against the SQL
text itself (that needs a live Postgres and belongs to `db/README.md`'s M2 checklist).
"""

from __future__ import annotations

import datetime as dt
from math import exp

import pytest

from services.api import ranking


def _sql_shape_priority(
    *,
    severity: float | None,
    link_confidence: float | None,
    report_date: dt.date | None,
    manager_flagged: bool,
    today: dt.date,
) -> int:
    """Mirrors `db/priority._REFRESH_ALL_SQL`'s arithmetic exactly: COALESCE/GREATEST on
    `CURRENT_DATE - report_date` (a plain day-count in Postgres), then the same four terms."""
    sev = severity if severity is not None else ranking.DEFAULT_SEVERITY
    link = link_confidence if link_confidence is not None else 0.0
    age_days = (today - report_date).days if report_date is not None else ranking.UNDATED_AGE_DAYS
    age_days = max(age_days, 0)
    recency = exp(-age_days / ranking.RECENCY_HALFLIFE_DAYS)
    manager = 1.0 if manager_flagged else 0.0
    return round(
        100
        * (
            ranking.W_SEVERITY * sev
            + ranking.W_LINK * link
            + ranking.W_RECENCY * recency
            + ranking.W_MANAGER * manager
        )
    )


def _ranking_priority(
    *,
    severity_weights: tuple[float, ...],
    link_confidence: float | None,
    report_date: dt.date | None,
    manager_flagged: bool,
    today: dt.date,
) -> int:
    return ranking.priority(
        ranking.ScoreInput(
            severity_weights=severity_weights,
            best_link_confidence=link_confidence,
            report_date=report_date,
            manager_flagged=manager_flagged,
        ),
        today,
    )


TODAY = dt.date(2026, 9, 9)


@pytest.mark.parametrize(
    "severity_weights,link_confidence,report_date,manager_flagged",
    [
        ((0.95,), 0.8, dt.date(2026, 9, 1), False),  # dated, high severity
        ((), None, None, False),  # no hazards, no link, no date - the "unknown risk" default
        ((0.6, 0.9), 0.3, dt.date(2020, 1, 1), True),  # multiple hazards, max wins; manager flag
        ((0.5,), 1.0, TODAY, False),  # today - recency term should be ~1.0
        ((0.4,), 0.0, dt.date(2027, 1, 1), False),  # future-dated - not "more urgent" than today
    ],
)
def test_sql_shape_matches_ranking_priority(
    severity_weights: tuple[float, ...],
    link_confidence: float | None,
    report_date: dt.date | None,
    manager_flagged: bool,
) -> None:
    expected = _ranking_priority(
        severity_weights=severity_weights,
        link_confidence=link_confidence,
        report_date=report_date,
        manager_flagged=manager_flagged,
        today=TODAY,
    )
    actual = _sql_shape_priority(
        severity=max(severity_weights, default=None),
        link_confidence=link_confidence,
        report_date=report_date,
        manager_flagged=manager_flagged,
        today=TODAY,
    )
    assert actual == expected
