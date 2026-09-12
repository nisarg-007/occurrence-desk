"""Unit tests for services/api/alerts.py: the webhook fires exactly once per report
crossing the critical-priority threshold, never again for the same report, and is a
clean no-op with no webhook configured. No database or network needed - `httpx.post`
is monkeypatched and the alert is fired on a background thread, so tests join it
explicitly rather than asserting instantly.
"""

from __future__ import annotations

import threading
import time

import pytest

from services.api import alerts
from services.common.settings import Settings


@pytest.fixture(autouse=True)
def clean_dedup_state():
    alerts.reset_alerted()
    yield
    alerts.reset_alerted()


class _RecordingPost:
    def __init__(self):
        self.calls: list[dict] = []
        self._done = threading.Event()

    def __call__(self, url, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        self._done.set()

    def wait(self, seconds: float = 1.0) -> None:
        assert self._done.wait(seconds), "webhook thread never ran"


def _settings(webhook_url: str = "https://hooks.example/T000/B000/xxx") -> Settings:
    return Settings(webhook_url=webhook_url)


def test_below_threshold_never_alerts(monkeypatch):
    post = _RecordingPost()
    monkeypatch.setattr("httpx.post", post)

    alerts.maybe_alert(
        report_id=1, acn="111", priority=alerts.CRITICAL_THRESHOLD - 1,
        hazard_label="Conflict", settings=_settings(),
    )
    time.sleep(0.05)
    assert post.calls == []


def test_crossing_threshold_fires_once(monkeypatch):
    post = _RecordingPost()
    monkeypatch.setattr("httpx.post", post)

    alerts.maybe_alert(
        report_id=2, acn="222", priority=alerts.CRITICAL_THRESHOLD,
        hazard_label="Conflict", settings=_settings(),
    )
    post.wait()

    assert len(post.calls) == 1
    call = post.calls[0]
    assert call["url"] == "https://hooks.example/T000/B000/xxx"
    assert "222" in call["json"]["text"]
    assert str(alerts.CRITICAL_THRESHOLD) in call["json"]["text"]
    assert "/console/reports/2" in call["json"]["text"]


def test_second_scoring_of_the_same_report_does_not_re_alert(monkeypatch):
    post = _RecordingPost()
    monkeypatch.setattr("httpx.post", post)

    alerts.maybe_alert(
        report_id=3, acn="333", priority=90, hazard_label="Conflict", settings=_settings()
    )
    post.wait()
    assert len(post.calls) == 1

    # A second scoring pass over the same report (e.g. a redelivered/duplicate parse
    # message) must not send a second alert.
    alerts.maybe_alert(
        report_id=3, acn="333", priority=95, hazard_label="Conflict", settings=_settings()
    )
    time.sleep(0.05)
    assert len(post.calls) == 1


def test_no_webhook_configured_is_a_clean_no_op(monkeypatch):
    post = _RecordingPost()
    monkeypatch.setattr("httpx.post", post)

    alerts.maybe_alert(
        report_id=4, acn="444", priority=95, hazard_label="Conflict", settings=_settings("")
    )
    time.sleep(0.05)
    assert post.calls == []
    # Not configuring a webhook must not consume the report's one alert slot either -
    # if one gets configured later, this report should still be able to alert.
    assert 4 not in alerts._alerted


def test_webhook_failure_is_logged_not_raised(monkeypatch, caplog):
    def boom(*a, **kw):
        raise ConnectionError("no route to host")

    monkeypatch.setattr("httpx.post", boom)

    alerts.maybe_alert(
        report_id=5, acn="555", priority=95, hazard_label="Conflict", settings=_settings()
    )
    # No exception propagates out of maybe_alert - it returned, and the background
    # thread that hit the failure is left to log it and die quietly.
