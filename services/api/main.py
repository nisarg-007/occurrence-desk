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

from services.api import charts, latency, metrics, presentation, problems
from services.api.deps import analyst, get_repo
from services.api.deps import settings as settings_dep
from services.api.problems import ApiProblem, problem_response
from services.api.routers import auth, documents, ops, queue, reports
from services.api.security import Principal, issue_token
from services.common import logging as jlog
from services.common.settings import Settings, get_settings

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

#: Sampled as the dashboard polls, so the latency line is this process's own measurements.
LATENCY = latency.LatencyHistory()
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


@app.get("/console/dashboard", include_in_schema=False)
def console_dashboard(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "dashboard.html", {"api_prefix": API_PREFIX, "nav": "dashboard"}
    )


@app.get("/console/dev-session", include_in_schema=False)
def dev_session(s: Settings = Depends(settings_dep)):
    """A signed-in session without a login form - **local development only**.

    Auth itself is not removed and is not weakened: the API still requires a bearer token on
    every path, `require_role` still refuses an analyst on manager-only routes, and the
    negative RBAC tests still run. This endpoint only spares us typing a password into our
    own laptop. It 404s the moment APP_ENV is anything but 'local', and the console shows a
    badge whenever it is in use, so nobody can mistake this for how the deployed system
    behaves.
    """
    if not s.is_local:
        raise problems.not_found("route")
    return {
        "access_token": issue_token(2, "manager@occdesk.example", "manager"),
        "role": "manager",
        "note": "local development session - APP_ENV=local only",
    }


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


@app.get("/console/fragments/dashboard", include_in_schema=False)
def dashboard_fragment(
    request: Request,
    p: Principal = Depends(analyst),
    repo=Depends(get_repo),
):
    """Everything on the dashboard, computed here and drawn as SVG.

    Rendering the charts on the server keeps the console consistent with itself: one
    request returns a finished picture, there is no chart library to load, and the page
    behaves the same with the network off.
    """
    import datetime as dt
    from collections import Counter

    rows = repo.list_reports(cursor=None, page_size=5000)
    today = dt.date.today()
    priorities = [repo.priority(r) for r in rows]

    # --- priority distribution: four named bands, so the status palette is right here
    band_counts = Counter(presentation.level(v)[1] for v in priorities)
    band_colors = {
        "Critical": "var(--sev-critical)",
        "High": "var(--sev-high)",
        "Moderate": "var(--sev-moderate)",
        "Low": "var(--sev-low)",
    }
    bands = [
        charts.Datum(label, band_counts.get(label, 0), band_colors[label])
        for _, _, label in presentation.BANDS
    ]

    # --- hazard mix: one hue, labels carry identity, long tail folded into Other
    hazard_counts = Counter(h["label"] for r in rows for h in r.hazards)
    top = hazard_counts.most_common(7)
    other = sum(hazard_counts.values()) - sum(c for _, c in top)
    hazards = [charts.Datum(lab, n) for lab, n in top]
    if other:
        hazards.append(charts.Datum("Other", other))

    # --- intake by month over the last 12 months
    months, counts = [], []
    for back in range(11, -1, -1):
        anchor = (today.replace(day=1) - dt.timedelta(days=back * 30)).replace(day=1)
        months.append(anchor.strftime("%b"))
        counts.append(
            sum(
                1
                for r in rows
                if r.report_date
                and (r.report_date.year, r.report_date.month) == (anchor.year, anchor.month)
            )
        )

    # --- our own submit latency, read back out of the Prometheus histogram
    LATENCY.observe()
    sample = LATENCY.latest

    return TEMPLATES.TemplateResponse(
        request,
        "_dashboard.html",
        {
            "is_stub": getattr(repo, "is_stub", False),
            "total": len(rows),
            "open_count": sum(1 for r in rows if r.state in ("new", "triaged")),
            "critical": band_counts.get("Critical", 0),
            "median": sorted(priorities)[len(priorities) // 2] if priorities else 0,
            "unlinked_pct": (
                round(100 * sum(1 for r in rows if not r.best_link_confidence) / len(rows))
                if rows
                else 0
            ),
            "bands_svg": charts.bars(bands, title="Reports by priority band"),
            "hazards_svg": charts.bars(hazards, title="Reports by hazard category"),
            "intake_svg": charts.columns(months, counts, title="Reports by month", every=2),
            "latency_svg": charts.sparkline(
                LATENCY.p95_series,
                title="Submit latency p95",
                threshold=latency.SLO_SECONDS * 1000,
                threshold_label="200 ms target",
            ),
            "latency": sample,
            "samples": len(LATENCY),
            "bands": bands,
            "hazards": hazards,
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
