from __future__ import annotations


def test_healthz_needs_no_token_and_checks_nothing(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_reports_its_dependencies_separately(client):
    body = client.get("/readyz").json()
    assert set(body["checks"]) == {"database", "queue"}


def test_healthz_and_readyz_are_different_endpoints(client):
    """If they were the same, one slow query would make ECS kill healthy tasks in a loop."""
    assert client.get("/healthz").json() != client.get("/readyz").json()


def test_metrics_is_prometheus_text(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_openapi_document_matches_the_contract_invariants(client):
    spec = client.get("/openapi.json").json()
    complete = spec["paths"]["/api/v1/documents/{document_id}/complete"]["post"]
    assert "202" in complete["responses"], "complete must return 202, never 200"
    reports = spec["paths"]["/api/v1/reports"]["get"]
    names = {p["name"] for p in reports.get("parameters", [])}
    assert "cursor" in names and "offset" not in names
