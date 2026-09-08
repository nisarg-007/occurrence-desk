from __future__ import annotations

from fastapi import APIRouter, Depends

from services.api.deps import get_repo, manager, settings
from services.api.queue_stats import (
    MIN_MEANINGFUL_THROUGHPUT_PER_MIN,
    QueueStatsCache,
    Snapshot,
    drain_eta_seconds,
    fetch_from_sqs,
)
from services.api.repo import Repository
from services.api.schemas import QueueStats
from services.api.security import Principal
from services.common import aws
from services.common.settings import Settings

router = APIRouter(prefix="/queue", tags=["queue"])

_cache = QueueStatsCache()


@router.get("/stats", response_model=QueueStats)
def stats(
    p: Principal = Depends(manager),
    repo: Repository = Depends(get_repo),
    s: Settings = Depends(settings),
) -> QueueStats:
    def fetch() -> Snapshot:
        if not s.sqs_queue_url:
            return Snapshot(0, 0, None, 0, 0.0)
        return fetch_from_sqs(aws.sqs(), s.sqs_queue_url, s.sqs_dlq_url)

    _cache.ttl = s.queue_stats_cache_seconds
    snap = _cache.get(fetch)

    throughput = float(repo.parsed_in_last_60s())
    eta = drain_eta_seconds(snap.visible, throughput)
    return QueueStats(
        visible=snap.visible,
        in_flight=snap.in_flight,
        oldest_message_age_seconds=snap.oldest_message_age_seconds,
        dlq_depth=snap.dlq_depth,
        # RunningTaskCount comes from ECS/ContainerInsights via Sowmya's metric plumbing.
        # Until that is wired, report in-flight messages as a floor rather than inventing a number.
        workers=min(snap.in_flight, 10) if snap.in_flight else 1,
        throughput_per_min=throughput,
        drain_eta_seconds=eta,
        estimating=throughput < MIN_MEANINGFUL_THROUGHPUT_PER_MIN,
        cached_for_seconds=s.queue_stats_cache_seconds,
    )
