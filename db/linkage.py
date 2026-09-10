"""The probabilistic join between a de-identified ASRS report and a real BTS flight — work
pack §2.4, called "the single most interesting query in the project."

**A deliberate, documented departure from the work pack's illustrative SQL.** §2.4 sketches
a candidate query joining on `f.aircraft_type` and comparing it to the report's
`make_model_name` via `pg_trgm` `similarity()`. That column does not exist in the real BTS
Reporting Carrier On-Time Performance file (§0.2's confirmed field list has no aircraft-type
or model field anywhere in it — only `Tail_Number`, which ASRS strips from every report on
purpose). Shipping a query that silently joins against a column the real data doesn't have,
or fabricating one, would be exactly the kind of invented number the whole project's honesty
clause exists to rule out. So this version scores on the three signals that are real on both
sides of the join:

  date_exact     the report's date matches a flight's date exactly
  date_near      within one day either side (ASRS reporters get dates wrong; BTS doesn't)
  operator_hit   the report's stated operator/airline text appears in `carriers.name`,
                 via `pg_trgm` `similarity()` - fuzzy, because a reporter writes "Southwest"
                 and BTS's carrier name field says something else entirely

`aircraft type` and `ATC facility` hints from the report's NASA coded fields are real and
are stored (verbatim, in `report_fields`) - they're just not currently joinable against
anything in the BTS schema itself, since BTS doesn't publish aircraft type per flight and
its facility/route fields don't align with ATC facility identifiers. Re-adding a term here
is a `report_fields` query plus one more `LinkageWeight` row, not a schema change - but it
needs a real column to score against on the flights side, which is a conversation for
whichever lane's data can supply one (T-100 segment data has an aircraft-type field; BTS
on-time performance does not).

Confidence never claims certainty a de-identified report can't support - see
`docs/measurements.md` for the honest top-1 rate against hand-checked reports.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import Numeric, func, literal, select
from sqlalchemy.orm import Session

from db.models import Carrier, Flight, LinkageWeight, ReportField

_DEFAULT_WEIGHTS = {"date_exact": 0.60, "date_near": 0.20, "operator_hit": 0.20}


@dataclass(frozen=True)
class FlightCandidate:
    flight_id: int
    confidence: float
    method: str
    flight_date: dt.date
    carrier_name: str | None


def _weights(session: Session) -> dict[str, float]:
    rows = session.execute(select(LinkageWeight.key, LinkageWeight.weight)).all()
    weights = dict(_DEFAULT_WEIGHTS)
    weights.update({key: float(weight) for key, weight in rows})
    return weights


def _operator_hint(session: Session, report_id: int) -> str | None:
    """The reporter's stated operator/airline, pulled from whichever NASA field path
    happened to carry it - `Aircraft.Aircraft Operator` for a numbered `Aircraft: N` block,
    kept verbatim by Smit's extractor (work pack §3.4), so the path always ends the same way
    regardless of the block number."""
    return session.scalar(
        select(ReportField.value)
        .where(
            ReportField.report_id == report_id,
            ReportField.path.ilike("%Aircraft Operator%"),
        )
        .limit(1)
    )


def candidate_flights(
    session: Session, report_id: int, *, report_date: dt.date | None, limit: int = 5
) -> list[FlightCandidate]:
    """Scored top-`limit` flight candidates for one report, best first. Empty when the
    report has no date (nothing to range-scan on) - an empty result is the honest answer,
    not an error."""
    if report_date is None:
        return []

    w = _weights(session)
    operator_hint = _operator_hint(session, report_id)

    # `date - date` is a plain integer day-count in Postgres (both sides are `date`) - no
    # `extract('epoch', ...)` needed, and using it here would be wrong (that function expects
    # an interval/timestamp, not the integer a date subtraction already is).
    date_exact = (Flight.flight_date == report_date).cast(Numeric)
    date_near = (func.abs(Flight.flight_date - report_date) <= 1).cast(Numeric)
    if operator_hint:
        operator_hit = (func.similarity(Carrier.name, literal(operator_hint)) > 0.3).cast(Numeric)
    else:
        operator_hit = literal(0).cast(Numeric)

    confidence = func.least(
        1.0,
        w["date_exact"] * date_exact
        + w["date_near"] * date_near
        + w["operator_hit"] * operator_hit,
    )

    stmt = (
        select(
            Flight.id,
            confidence.label("confidence"),
            Flight.flight_date,
            Carrier.name,
        )
        .join(Carrier, Carrier.dot_id == Flight.dot_id)
        .where(
            Flight.flight_date.between(
                report_date - dt.timedelta(days=1), report_date + dt.timedelta(days=1)
            )
        )
        .order_by(confidence.desc())
        .limit(limit)
    )
    rows = session.execute(stmt).all()
    return [
        FlightCandidate(
            flight_id=flight_id,
            confidence=float(conf),
            method="date+operator" if operator_hint else "date_only",
            flight_date=flight_date,
            carrier_name=carrier_name,
        )
        for flight_id, conf, flight_date, carrier_name in rows
        if conf > 0
    ]


def link_best_candidate(session: Session, report_id: int, report_date: dt.date | None) -> None:
    """Writes the top scored candidate (if any) into `report_flight_links`. Called after a
    report is extracted or re-scored; safe to call again - it replaces the row rather than
    accumulating duplicates."""
    from db.models import ReportFlightLink

    candidates = candidate_flights(session, report_id, report_date=report_date, limit=1)
    session.query(ReportFlightLink).filter(ReportFlightLink.report_id == report_id).delete()
    if candidates:
        best = candidates[0]
        session.add(
            ReportFlightLink(
                report_id=report_id,
                flight_id=best.flight_id,
                confidence=best.confidence,
                method=best.method,
            )
        )
