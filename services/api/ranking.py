"""The ranked queue.

An analyst does not want a list of reports; they want the right report first. This score is
deterministic (so it can be tested) and explainable (so it will be trusted). Every term is one
sentence long, and `GET /reports/{id}/why` returns the four terms and their products.

The weights below are the *blend*. The per-category severity number is NOT here: it is
`hazard_categories.severity_weight`, a column, so it is data we can defend and change with a
dated row update rather than a magic number buried in code.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from math import exp

W_SEVERITY = 0.45
W_LINK = 0.25
W_RECENCY = 0.20
W_MANAGER = 0.10

#: Used when a report has no hazard rows at all - an unclassified report is not zero-risk,
#: it is unknown-risk, and burying it at the bottom of the queue would be the wrong default.
DEFAULT_SEVERITY = 0.30

#: A report with no date is treated as very old rather than dropped from the ordering.
UNDATED_AGE_DAYS = 3650

RECENCY_HALFLIFE_DAYS = 365.0

FORMULA = "100 * (0.45*severity + 0.25*link_confidence + 0.20*recency + 0.10*manager_flag)"


@dataclass(frozen=True)
class Term:
    name: str
    weight: float
    value: float
    explanation: str

    @property
    def product(self) -> float:
        return round(self.weight * self.value, 6)


@dataclass(frozen=True)
class ScoreInput:
    """Everything the score needs, and nothing else - so it is trivially testable."""

    severity_weights: tuple[float, ...] = ()
    best_link_confidence: float | None = None
    report_date: dt.date | None = None
    manager_flagged: bool = False


def recency(report_date: dt.date | None, today: dt.date) -> float:
    age_days = (today - report_date).days if report_date else UNDATED_AGE_DAYS
    age_days = max(age_days, 0)  # a future-dated report is not more urgent than today's
    return exp(-age_days / RECENCY_HALFLIFE_DAYS)


def terms(inp: ScoreInput, today: dt.date) -> list[Term]:
    sev = max(inp.severity_weights, default=DEFAULT_SEVERITY)
    link = inp.best_link_confidence or 0.0
    rec = recency(inp.report_date, today)
    flag = 1.0 if inp.manager_flagged else 0.0
    return [
        Term(
            "severity",
            W_SEVERITY,
            float(sev),
            "the severity weight of the most serious hazard category on this report",
        ),
        Term(
            "link_confidence",
            W_LINK,
            float(link),
            "how confidently this report is matched to a real BTS flight",
        ),
        Term(
            "recency",
            W_RECENCY,
            float(rec),
            f"exp(-age/{RECENCY_HALFLIFE_DAYS:.0f}d): a report a year old counts about a third "
            "of one filed today",
        ),
        Term(
            "manager_flag",
            W_MANAGER,
            flag,
            "a manager has flagged this report for attention",
        ),
    ]


def priority(inp: ScoreInput, today: dt.date) -> int:
    """0-100, deterministic."""
    return round(100 * sum(t.product for t in terms(inp, today)))


def explain(inp: ScoreInput, today: dt.date) -> dict:
    ts = terms(inp, today)
    return {
        "priority": round(100 * sum(t.product for t in ts)),
        "formula": FORMULA,
        "terms": [
            {
                "name": t.name,
                "weight": t.weight,
                "value": round(t.value, 6),
                "product": t.product,
                "explanation": t.explanation,
            }
            for t in ts
        ],
    }
