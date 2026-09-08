"""The service measures its own latency, because the headline claim is a latency number."""

from __future__ import annotations

import re


def _samples(body: str, name: str) -> list[str]:
    return [ln for ln in body.splitlines() if ln.startswith(name) and not ln.startswith("#")]


def test_metrics_exposes_a_request_duration_histogram(client, analyst_headers):
    client.get("/api/v1/reports", headers=analyst_headers)
    body = client.get("/metrics").text
    assert "occdesk_http_request_duration_seconds_bucket" in body
    assert "occdesk_http_request_duration_seconds_count" in body


def test_histogram_has_a_bucket_edge_on_the_200ms_target(client):
    """The p95 SLO is 200 ms. A bucket edge sitting exactly on it makes the dashboard query a
    division, not an interpolation between neighbouring buckets."""
    from services.api.metrics import LATENCY_BUCKETS

    assert 0.2 in LATENCY_BUCKETS
    body = client.get("/metrics").text
    assert 'le="0.2"' in body


def test_labels_use_the_route_template_not_the_raw_path(client, analyst_headers):
    """Labelling by raw path would mint a time series per report id. Unbounded label
    cardinality is the standard way to melt a Prometheus."""
    client.get("/api/v1/reports/1", headers=analyst_headers)
    client.get("/api/v1/reports/2", headers=analyst_headers)
    body = client.get("/metrics").text
    assert 'route="/api/v1/reports/{report_id}"' in body
    assert 'route="/api/v1/reports/1"' not in body


def test_unmatched_paths_share_one_series(client):
    client.get("/definitely-not-a-route-1")
    client.get("/definitely-not-a-route-2")
    body = client.get("/metrics").text
    assert 'route="unmatched"' in body
    assert "definitely-not-a-route" not in body


def test_status_is_a_label_so_errors_are_separable(client):
    client.get("/api/v1/reports")  # 401, no token
    body = client.get("/metrics").text
    assert re.search(r'status="401"', body)


def test_build_info_carries_the_version(client):
    assert "occdesk_build_info" in client.get("/metrics").text


def test_metrics_needs_no_token(client):
    """A scraper that needs a JWT is a scraper that stops working at 3am."""
    assert client.get("/metrics").status_code == 200
