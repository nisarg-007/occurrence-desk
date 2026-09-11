"""Keeps `reports.priority` in sync with `services/api/ranking.py`'s formula.

Why this exists instead of a Postgres `GENERATED ALWAYS AS` column: the recency term is
`exp(-(today - report_date).days / 365)`, and `today` is not immutable, so Postgres refuses
a STORED generated column built on it. The formula is duplicated here in SQL, deliberately
kept in lockstep with `ranking.py` (same weights, same default severity, same undated-age
fallback) - if one changes, this one must change in the same PR, and
`tests/unit/test_priority_sql_matches_ranking.py` fails loudly if they drift.

`refresh_priorities` is cheap enough to call after any single-report write (a new hazard, a
new flight link, a manager flag) and is also safe to run over the whole table on a schedule,
which is what actually keeps recency from drifting stale for reports nobody touches.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.api.ranking import (
    DEFAULT_SEVERITY,
    RECENCY_HALFLIFE_DAYS,
    UNDATED_AGE_DAYS,
    W_LINK,
    W_MANAGER,
    W_RECENCY,
    W_SEVERITY,
)

#: One UPDATE, correlated subqueries - no row-by-row Python loop. Matches `ranking.terms()`
#: term for term:
#:   severity   = MAX(hazard_categories.severity_weight) over this report's hazards, or
#:                DEFAULT_SEVERITY when it has none
#:   link       = MAX(report_flight_links.confidence) for this report, or 0
#:   recency    = exp(-age_days / halflife); age_days uses UNDATED_AGE_DAYS when report_date
#:                is null, and is floored at 0 so a future-dated report isn't "more urgent"
#:   manager    = 1.0 if manager_flagged else 0.0
# `CURRENT_DATE - r.report_date` is a plain integer day-count in Postgres (both sides are
# `date`) - no EXTRACT needed.
_REFRESH_ALL_SQL = f"""
UPDATE reports r
SET priority = ROUND(
    100 * (
        {W_SEVERITY} * COALESCE(
            (SELECT MAX(hc.severity_weight)
             FROM report_hazards rh JOIN hazard_categories hc ON hc.id = rh.category_id
             WHERE rh.report_id = r.id),
            {DEFAULT_SEVERITY}
        ) +
        {W_LINK} * COALESCE(
            (SELECT MAX(rfl.confidence) FROM report_flight_links rfl
             WHERE rfl.report_id = r.id),
            0
        ) +
        {W_RECENCY} * EXP(
            -GREATEST(COALESCE(CURRENT_DATE - r.report_date, {UNDATED_AGE_DAYS}), 0)::numeric
            / {RECENCY_HALFLIFE_DAYS}
        ) +
        {W_MANAGER} * (CASE WHEN r.manager_flagged THEN 1.0 ELSE 0.0 END)
    )
)::int
WHERE 1 = 1
{{report_filter}}
"""


def refresh_priorities(session: Session, *, report_id: int | None = None) -> int:
    """Recompute `reports.priority` for one report, or every report when `report_id` is None.

    Returns the number of rows updated. Call this after writing a hazard, a flight link, a
    manager flag, or (rarely - it's for the demo, not the hot path) on a schedule so pure
    recency drift stays bounded for untouched reports.
    """
    if report_id is not None:
        # `r`, not `r2`: the UPDATE aliases `reports` as `r`. The original
        # `AND r2.id = :report_id` referenced an alias that does not exist, so
        # every single-report refresh raised UndefinedTable. It survived review
        # because this module was only ever compiled and logic-cross-checked -
        # never executed against a live Postgres until the merge on `try-main`.
        sql = _REFRESH_ALL_SQL.format(report_filter="AND r.id = :report_id")
        result = session.execute(text(sql), {"report_id": report_id})
    else:
        sql = _REFRESH_ALL_SQL.format(report_filter="")
        result = session.execute(text(sql))
    return result.rowcount or 0  # type: ignore[attr-defined]  # CursorResult at runtime
