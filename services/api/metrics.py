"""Prometheus metrics.

The project's headline claim is a latency number: `POST /documents/{id}/complete` under 200 ms
at p95 while the queue is deep. A claim that can only be measured from outside the service is a
claim we cannot defend in the demo, so the service measures itself and Sowmya's dashboard reads
these series.

**Label on the route template, never the raw path.** `/reports/4412` and `/reports/4413` are the
same endpoint; labelling by raw path would mint a new time series per report id, and unbounded
label cardinality is the standard way to melt a Prometheus.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

#: Buckets chosen around the 200 ms p95 target, not the library default: the interesting
#: region is 50-500 ms, and a bucket edge sitting exactly on the SLO makes the dashboard
#: query a division rather than an interpolation.
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0)

request_duration = Histogram(
    "occdesk_http_request_duration_seconds",
    "HTTP request duration",
    labelnames=("method", "route", "status"),
    buckets=LATENCY_BUCKETS,
)

documents_submitted = Counter(
    "occdesk_documents_submitted_total",
    "POST /documents/{id}/complete calls that returned 202",
    labelnames=("enqueued",),  # false == a duplicate submission collapsed by sha256
)

build_info = Gauge("occdesk_build_info", "Build information", labelnames=("version",))


def route_of(request) -> str:
    """The matched route template, or a single bucket for anything unmatched.

    Unmatched paths (scanners, typos) all share one series on purpose - otherwise a bot
    walking random URLs would create a metric per URL.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
