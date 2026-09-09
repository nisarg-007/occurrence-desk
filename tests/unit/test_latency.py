"""A histogram gives bucket counts, not exact percentiles - `quantile()` estimates by linear
interpolation within a bucket, the same estimator Prometheus itself uses. These tests build a
throwaway registry so they exercise the real `_buckets`/`quantile` path, not a mock of it."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Histogram

from services.api import latency


def _histogram(observations: list[float]) -> CollectorRegistry:
    registry = CollectorRegistry()
    h = Histogram(
        "occdesk_http_request_duration_seconds",
        "test histogram",
        labelnames=["route"],
        buckets=(0.05, 0.1, 0.2, 0.5, 1.0),
        registry=registry,
    )
    for v in observations:
        h.labels(route="/x").observe(v)
    return registry


def test_quantile_is_none_with_no_observations(monkeypatch):
    monkeypatch.setattr(latency, "REGISTRY", CollectorRegistry())
    assert latency.quantile(0.95) is None


def test_quantile_of_uniform_bucket_hit_matches_the_bucket_bound(monkeypatch):
    """Ten observations, all in the same bucket: p50 must land at or below that bucket's
    upper bound, and strictly above the previous one."""
    monkeypatch.setattr(latency, "REGISTRY", _histogram([0.07] * 10))
    q = latency.quantile(0.5, route="/x")
    assert 0.05 < q <= 0.1


def test_quantile_interpolates_between_buckets(monkeypatch):
    # 5 fast (in the 0.05 bucket) + 5 slow (in the 0.2 bucket): p50 sits at the boundary
    # between them, near the 0.1 bucket edge where the cumulative count first reaches half.
    monkeypatch.setattr(latency, "REGISTRY", _histogram([0.02] * 5 + [0.15] * 5))
    q = latency.quantile(0.5, route="/x")
    assert 0.05 <= q <= 0.2


def test_quantile_p95_is_at_least_p50(monkeypatch):
    monkeypatch.setattr(latency, "REGISTRY", _histogram([0.02, 0.04, 0.08, 0.3, 0.9]))
    p50 = latency.quantile(0.50, route="/x")
    p95 = latency.quantile(0.95, route="/x")
    assert p95 >= p50


def test_quantile_filters_by_route(monkeypatch):
    registry = CollectorRegistry()
    h = Histogram(
        "occdesk_http_request_duration_seconds",
        "test histogram",
        labelnames=["route"],
        buckets=(0.05, 0.1, 0.2),
        registry=registry,
    )
    h.labels(route="/fast").observe(0.01)
    h.labels(route="/slow").observe(0.19)
    monkeypatch.setattr(latency, "REGISTRY", registry)
    assert latency.quantile(0.5, route="/fast") < latency.quantile(0.5, route="/slow")


def test_latency_history_observe_returns_none_before_any_requests(monkeypatch):
    monkeypatch.setattr(latency, "REGISTRY", CollectorRegistry())
    history = latency.LatencyHistory()
    assert history.observe() is None
    assert history.latest is None
    assert len(history) == 0


def test_latency_history_records_a_sample_in_milliseconds(monkeypatch):
    monkeypatch.setattr(latency, "REGISTRY", _histogram([0.05] * 10))
    history = latency.LatencyHistory()
    sample = history.observe(route="/x")
    assert sample is not None
    assert sample.count == 10
    assert sample.p95_ms > sample.p50_ms - 1  # p95 is never below p50 within float slop
    assert sample.p50_ms < 1000  # sane units - milliseconds, not seconds or microseconds


def test_latency_history_ring_buffer_is_bounded():
    history = latency.LatencyHistory(size=3)
    for s in range(5):
        history._samples.append(latency.Sample(p50_ms=s, p95_ms=s, count=s))
    assert len(history) == 3
    assert history.p95_series == [2, 3, 4]
