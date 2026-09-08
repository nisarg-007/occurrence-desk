from __future__ import annotations

from services.api.queue_stats import QueueStatsCache, Snapshot, drain_eta_seconds


def test_eta_is_null_while_throughput_is_meaningless():
    """A wrong number is worse than no number - the console shows 'estimating'."""
    assert drain_eta_seconds(10_000, 0.0) is None
    assert drain_eta_seconds(10_000, 0.5) is None


def test_eta_is_backlog_over_throughput():
    # 600 messages at 60 per minute == 1 per second == 600 seconds.
    assert drain_eta_seconds(600, 60.0) == 600


def test_get_queue_attributes_is_cached_so_the_console_cannot_hammer_sqs():
    clock = {"t": 0.0}
    calls = {"n": 0}

    def fetch() -> Snapshot:
        calls["n"] += 1
        return Snapshot(1, 0, None, 0, 0.0)

    cache = QueueStatsCache(ttl_seconds=5, clock=lambda: clock["t"])
    for _ in range(20):
        cache.get(fetch)
    assert calls["n"] == 1

    clock["t"] = 5.1
    cache.get(fetch)
    assert calls["n"] == 2
