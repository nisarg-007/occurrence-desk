"""Reading our own latency back out of the Prometheus histogram.

The project's headline claim is a number: submit stays under 200 ms at p95. A claim that can
only be measured from outside the service is one we cannot show on a screen during the demo,
so the service reads its own histogram and the dashboard draws it.

Quantiles from a histogram are **estimates**, not exact percentiles: we know how many
observations fell in each bucket, not where inside the bucket they fell. Linear interpolation
within the bucket is the standard estimator and it is what Prometheus itself does. The
dashboard says "estimated" for that reason - a number presented as more precise than it is
would be worse than no number.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from prometheus_client import REGISTRY

#: p95 target from the definition of done, in seconds.
SLO_SECONDS = 0.200

#: One sample per dashboard poll. 120 samples at a 5 s poll is the last ten minutes, which is
#: longer than the demo and short enough to stay in memory forever without care.
HISTORY = 120


@dataclass
class Sample:
    p50_ms: float
    p95_ms: float
    count: int


def _buckets(metric_name: str, route: str | None) -> tuple[list[tuple[float, float]], float]:
    """(cumulative buckets sorted by upper bound, total count) for the matching series."""
    acc: dict[float, float] = {}
    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name != metric_name:
            continue
        for s in metric.samples:
            if route is not None and s.labels.get("route") != route:
                continue
            if s.name.endswith("_bucket"):
                le = float(s.labels["le"])
                acc[le] = acc.get(le, 0.0) + s.value
            elif s.name.endswith("_count"):
                total += s.value
    return sorted(acc.items()), total


def quantile(q: float, route: str | None = None) -> float | None:
    """Estimated quantile in seconds, or None when there is nothing to estimate from."""
    buckets, total = _buckets("occdesk_http_request_duration_seconds", route)
    if not buckets or total <= 0:
        return None

    target = q * total
    prev_bound, prev_count = 0.0, 0.0
    for bound, cumulative in buckets:
        if cumulative >= target:
            if bound == float("inf"):
                return prev_bound
            span = cumulative - prev_count
            if span <= 0:
                return bound
            # linear interpolation inside the bucket
            return prev_bound + (bound - prev_bound) * ((target - prev_count) / span)
        prev_bound, prev_count = bound, cumulative
    return prev_bound


class LatencyHistory:
    """A ring of samples taken as the dashboard polls. Explicitly 'since this process
    started' - it is not persisted, and the dashboard says so."""

    def __init__(self, size: int = HISTORY) -> None:
        self._samples: deque[Sample] = deque(maxlen=size)

    def observe(self, route: str | None = None) -> Sample | None:
        p50, p95 = quantile(0.50, route), quantile(0.95, route)
        if p50 is None or p95 is None:
            return None
        _, total = _buckets("occdesk_http_request_duration_seconds", route)
        sample = Sample(p50_ms=p50 * 1000, p95_ms=p95 * 1000, count=int(total))
        self._samples.append(sample)
        return sample

    @property
    def p95_series(self) -> list[float]:
        return [s.p95_ms for s in self._samples]

    @property
    def latest(self) -> Sample | None:
        return self._samples[-1] if self._samples else None

    def __len__(self) -> int:
        return len(self._samples)
