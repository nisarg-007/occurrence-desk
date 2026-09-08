from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, status

from services.api import problems, ranking
from services.api.deps import analyst, get_repo, manager
from services.api.pagination import Cursor, InvalidCursor
from services.api.repo import Repository
from services.api.routers.documents import _summary
from services.api.schemas import (
    AssignRequest,
    Disposition,
    DispositionRequest,
    FlightLink,
    Hazard,
    PriorityExplanation,
    ReportDetail,
    ReportPage,
    ReportSummary,
)
from services.api.security import Principal

router = APIRouter(prefix="/reports", tags=["reports"])


def _score_input(r) -> ranking.ScoreInput:
    return ranking.ScoreInput(
        severity_weights=r.severity_weights,
        best_link_confidence=r.best_link_confidence,
        report_date=r.report_date,
        manager_flagged=r.manager_flagged,
    )


@router.get("", response_model=ReportPage)
def list_reports(
    category: str | None = None,
    state: str | None = None,
    priority_min: int | None = Query(default=None, ge=0, le=100),
    flight_date: dt.date | None = None,
    q: str | None = None,
    cursor: str | None = None,
    page_size: int = Query(default=50, ge=1, le=200),
    p: Principal = Depends(analyst),
    repo: Repository = Depends(get_repo),
) -> ReportPage:
    parsed: Cursor | None = None
    if cursor:
        try:
            parsed = Cursor.decode(cursor)
        except InvalidCursor as exc:
            raise problems.ApiProblem(422, "Invalid Cursor", str(exc)) from exc

    rows = repo.list_reports(
        cursor=parsed,
        page_size=page_size,
        category=category,
        state=state,
        priority_min=priority_min,
        q=q,
    )
    # The repository returns page_size + 1 rows; the extra one only tells us a next page exists.
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items = [_summary(repo, r) for r in rows]
    next_cursor = (
        Cursor(items[-1].priority, items[-1].report_date, items[-1].id).encode()
        if has_more and items
        else None
    )
    return ReportPage(items=items, next_cursor=next_cursor, page_size=page_size)


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(
    report_id: int,
    p: Principal = Depends(analyst),
    repo: Repository = Depends(get_repo),
) -> ReportDetail:
    r = repo.report(report_id)
    if r is None:
        raise problems.not_found("report")
    return ReportDetail(
        id=r.id,
        acn=r.acn,
        report_date=r.report_date,
        synopsis=r.synopsis,
        priority=repo.priority(r),
        state=r.state,
        assigned_to=r.assigned_to,
        hazards=[Hazard(**h) for h in r.hazards],
        document_id=r.document_id,
        narrative=r.narrative,
        coded=r.coded,
        linked_flight=FlightLink(**r.linked_flight) if r.linked_flight else None,
    )


@router.get("/{report_id}/why", response_model=PriorityExplanation)
def why(
    report_id: int,
    p: Principal = Depends(analyst),
    repo: Repository = Depends(get_repo),
) -> PriorityExplanation:
    """Twenty minutes of work, and the single best thing to have on screen in the demo."""
    r = repo.report(report_id)
    if r is None:
        raise problems.not_found("report")
    payload = ranking.explain(_score_input(r), dt.date.today())
    return PriorityExplanation(report_id=r.id, **payload)


@router.post(
    "/{report_id}/disposition", response_model=Disposition, status_code=status.HTTP_201_CREATED
)
def disposition(
    report_id: int,
    body: DispositionRequest,
    p: Principal = Depends(analyst),
    repo: Repository = Depends(get_repo),
) -> Disposition:
    r = repo.report(report_id)
    if r is None:
        raise problems.not_found("report")
    # An analyst may only dispose of their own assignments; a manager may dispose of anything.
    if not p.has("manager") and r.assigned_to not in (None, p.user_id):
        raise problems.forbidden("this report is assigned to another analyst")
    row = repo.add_disposition(
        report_id, p.user_id, state=body.state, priority=body.priority, note=body.note
    )
    return Disposition(**row)


@router.patch("/{report_id}/assign", response_model=ReportSummary)
def assign(
    report_id: int,
    body: AssignRequest,
    p: Principal = Depends(manager),  # analyst tokens get 403 here - tests/contract/test_rbac.py
    repo: Repository = Depends(get_repo),
) -> ReportSummary:
    r = repo.assign(report_id, body.analyst_id, body.manager_flagged)
    if r is None:
        raise problems.not_found("report")
    return _summary(repo, r)
