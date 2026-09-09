"""Occurrence Desk API.

Everything the analyst touches, plus the contract every other lane codes against.
Run locally:  APP_ENV=local uvicorn services.api.main:app --reload
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from services.api import metrics, presentation, problems
from services.api.deps import analyst, get_repo
from services.api.problems import ApiProblem, problem_response
from services.api.routers import auth, documents, ops, queue, reports
from services.api.security import Principal
from services.common import logging as jlog
from services.common.settings import get_settings

settings = get_settings()
jlog.configure("api", settings.log_level)

app = FastAPI(
    title="Occurrence Desk API",
    version="1.0.0",
    description="Aviation safety report triage. Contract: contracts/openapi.yaml",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

API_PREFIX = "/api/v1"
PAGE_SIZE = 25
WEB = Path(__file__).resolve().parents[2] / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB / "templates"))


@app.middleware("http")
async def request_context(request: Request, call_next):
    """One id per request, echoed as X-Request-Id and carried into every log line.

    The client may supply X-Request-Id (Sowmya's harness does, so a load-test row can be traced
    straight into CloudWatch); otherwise we mint one.
    """
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    jlog.request_id_var.set(request_id)
    jlog.trace_id_var.set(request.headers.get("x-trace-id") or request_id)

    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)

    response.headers["X-Request-Id"] = request_id
    metrics.request_duration.labels(
        method=request.method, route=metrics.route_of(request), status=response.status_code
    ).observe(duration_ms / 1000.0)

    import logging

    logging.getLogger("api.access").info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.exception_handler(ApiProblem)
async def _problem(request: Request, exc: ApiProblem) -> JSONResponse:
    return problem_response(request, exc)


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    return problem_response(
        request, problems.ApiProblem(422, "Validation Error", str(exc.errors()))
    )


for r in (auth.router, documents.router, reports.router, queue.router):
    app.include_router(r, prefix=API_PREFIX)
app.include_router(ops.router)  # /healthz /readyz /metrics stay unversioned for the ALB

metrics.build_info.labels(version=settings.app_version).set(1)

# Vendored, not a CDN: the console has to render with the wifi off, and a blocked
# script would leave the worklist saying "loading" forever.
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")


# --- the analyst console ------------------------------------------------------
# Server-rendered Jinja2 + HTMX. A page that renders on the server cannot show a spinner
# forever, and the worklist has to stay responsive while the backlog is still draining.


@app.get("/console", include_in_schema=False)
def console(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "worklist.html", {"api_prefix": API_PREFIX, "nav": "worklist"}
    )


@app.get("/console/login", include_in_schema=False)
def console_login(request: Request):
    return TEMPLATES.TemplateResponse(request, "login.html", {"api_prefix": API_PREFIX})


@app.get("/console/upload", include_in_schema=False)
def console_upload(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "upload.html", {"api_prefix": API_PREFIX, "nav": "upload"}
    )


@app.get("/console/reports/{report_id}", include_in_schema=False)
def console_report(request: Request, report_id: int):
    """The page shell only. The data arrives through an authenticated fragment, because a
    browser navigation cannot carry a bearer token and we are not putting one in a cookie
    without CSRF protection we have not built yet."""
    return TEMPLATES.TemplateResponse(
        request, "report.html", {"api_prefix": API_PREFIX, "report_id": report_id}
    )


# Fragments carry the same auth as the API they render. A fragment endpoint left open is a
# data leak that does not look like one, because the page in front of it asks for a login.


@app.get("/console/fragments/worklist", include_in_schema=False)
def worklist_fragment(
    request: Request,
    cursor: str | None = None,
    p: Principal = Depends(analyst),
    repo=Depends(get_repo),
):
    """HTMX target. Returns rows only, so polling the list costs one small fragment."""
    from services.api.pagination import Cursor, InvalidCursor

    try:
        parsed = Cursor.decode(cursor) if cursor else None
    except InvalidCursor as exc:
        raise problems.ApiProblem(422, "Invalid Cursor", str(exc)) from exc

    rows = repo.list_reports(cursor=parsed, page_size=PAGE_SIZE)
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    items = [
        {
            "id": r.id,
            "acn": r.acn,
            "synopsis": r.synopsis,
            "report_date": r.report_date,
            "priority": repo.priority(r),
            "level": presentation.level(repo.priority(r))[0],
            "level_label": presentation.level(repo.priority(r))[1],
            "state": r.state,
            "hazards": r.hazards,
        }
        for r in rows
    ]
    next_cursor = (
        Cursor(items[-1]["priority"], items[-1]["report_date"], items[-1]["id"]).encode()
        if has_more and items
        else None
    )
    return TEMPLATES.TemplateResponse(
        request,
        "_rows.html",
        {"items": items, "next_cursor": next_cursor, "api_prefix": API_PREFIX},
    )


@app.get("/console/fragments/report/{report_id}", include_in_schema=False)
def report_fragment(
    request: Request,
    report_id: int,
    p: Principal = Depends(analyst),
    repo=Depends(get_repo),
):
    """The demo screen: the report, and the four numbers that put it where it is."""
    import datetime as dt

    from services.api import ranking

    r = repo.report(report_id)
    if r is None:
        raise problems.not_found("report")

    why = ranking.explain(
        ranking.ScoreInput(
            severity_weights=r.severity_weights,
            best_link_confidence=r.best_link_confidence,
            report_date=r.report_date,
            manager_flagged=r.manager_flagged,
        ),
        dt.date.today(),
    )
    band, band_label = presentation.level(why["priority"])
    return TEMPLATES.TemplateResponse(
        request,
        "_report.html",
        {
            "api_prefix": API_PREFIX,
            "r": r,
            "why": why,
            "level": band,
            "level_label": band_label,
        },
    )


@app.get("/console/fragments/stats", include_in_schema=False)
def stats_fragment(
    request: Request,
    p: Principal = Depends(analyst),
    repo=Depends(get_repo),
):
    """What an analyst actually wants at the top of the screen.

    This replaces the block of SQL-shaped text that used to sit there. Queue depth is
    manager-only, so analysts simply do not see those two tiles - the page does not
    show an empty box where a permission used to be.
    """
    rows = repo.list_reports(cursor=None, page_size=1000)
    priorities = sorted((repo.priority(r) for r in rows), reverse=True)
    queue = None
    if p.has("manager"):
        from services.api.queue_stats import MIN_MEANINGFUL_THROUGHPUT_PER_MIN, drain_eta_seconds

        throughput = float(repo.parsed_in_last_60s())
        eta = drain_eta_seconds(0, throughput)
        queue = {
            "visible": 0,
            "estimating": throughput < MIN_MEANINGFUL_THROUGHPUT_PER_MIN,
            "eta_minutes": round((eta or 0) / 60),
        }
    return TEMPLATES.TemplateResponse(
        request,
        "_stats.html",
        {
            "open_count": sum(1 for r in rows if r.state in ("new", "triaged")),
            "high_count": sum(1 for v in priorities if v >= 70),
            "top_priority": priorities[0] if priorities else None,
            "queue": queue,
        },
    )


@app.get("/", include_in_schema=False)
def root():
    return {
        "service": "occurrence-desk-api",
        "version": settings.app_version,
        "docs": "/docs",
        "console": "/console",
        "contract": "contracts/openapi.yaml",
    }


__all__ = ["app"]
