"""Liveness, readiness, metrics.

/healthz deliberately checks nothing. If readiness and liveness are the same endpoint, one slow
query makes ECS kill healthy tasks in a loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from services.api import metrics
from services.api.deps import settings
from services.api.schemas import Health, Readiness
from services.common import aws
from services.common.settings import Settings

router = APIRouter(tags=["ops"])


@router.get("/healthz", response_model=Health)
def healthz(s: Settings = Depends(settings)) -> Health:
    return Health(version=s.app_version)


@router.get("/readyz", response_model=Readiness)
def readyz(response: Response, s: Settings = Depends(settings)) -> Readiness:
    checks = {"database": _check_db(s), "queue": _check_queue(s)}
    ready = all(checks.values())
    response.status_code = 200 if ready else 503
    return Readiness(status="ready" if ready else "not_ready", checks=checks)


def _check_db(s: Settings) -> bool:
    if s.is_local:
        return True  # the M1 stub repository is always available
    try:
        from sqlalchemy import create_engine, text

        with create_engine(s.database_url, pool_pre_ping=True).connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - readiness reports false, it does not raise
        return False


def _check_queue(s: Settings) -> bool:
    if not s.sqs_queue_url:
        return True
    try:
        aws.sqs().get_queue_attributes(
            QueueUrl=s.sqs_queue_url, AttributeNames=["ApproximateNumberOfMessages"]
        )
        return True
    except Exception:  # noqa: BLE001
        return False


@router.get("/metrics")
def prometheus_metrics() -> Response:
    """Prometheus text exposition, served unauthenticated for the scraper.

    On AWS this path is not exposed through the public ALB listener - it is scraped inside the
    VPC. That is Wasim's listener rule; the endpoint itself deliberately has no token check,
    because a scraper that needs a JWT is a scraper that stops working at 3am.
    """
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)
