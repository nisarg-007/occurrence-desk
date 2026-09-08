"""RBAC that was never tested negatively is RBAC that does not exist.

One test per manager-only path. No loops that can silently pass on zero iterations.
"""

from __future__ import annotations


def test_analyst_gets_403_on_assign(client, analyst_headers):
    r = client.patch("/api/v1/reports/2/assign", json={"analyst_id": 1}, headers=analyst_headers)
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Forbidden"


def test_analyst_gets_403_on_queue_stats(client, analyst_headers):
    r = client.get("/api/v1/queue/stats", headers=analyst_headers)
    assert r.status_code == 403


def test_manager_may_assign(client, manager_headers):
    r = client.patch(
        "/api/v1/reports/2/assign",
        json={"analyst_id": 1, "manager_flagged": True},
        headers=manager_headers,
    )
    assert r.status_code == 200
    assert r.json()["assigned_to"] == 1


def test_manager_may_read_queue_stats(client, manager_headers):
    r = client.get("/api/v1/queue/stats", headers=manager_headers)
    assert r.status_code == 200
    assert set(r.json()) >= {"visible", "workers", "throughput_per_min", "estimating"}


def test_no_token_is_401_not_403(client):
    assert client.get("/api/v1/reports").status_code == 401


def test_garbage_token_is_401(client):
    r = client.get("/api/v1/reports", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_login_does_not_distinguish_unknown_email_from_wrong_password(client):
    a = client.post(
        "/api/v1/auth/login", json={"email": "nobody@occdesk.example", "password": "occdesk-local"}
    )
    b = client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@occdesk.example", "password": "wrong-password"},
    )
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_manager_flag_raises_priority_by_ten(client, manager_headers, analyst_headers):
    before = client.get("/api/v1/reports/2", headers=analyst_headers).json()["priority"]
    client.patch(
        "/api/v1/reports/2/assign",
        json={"analyst_id": 1, "manager_flagged": True},
        headers=manager_headers,
    )
    after = client.get("/api/v1/reports/2", headers=analyst_headers).json()["priority"]
    assert after - before == 10
