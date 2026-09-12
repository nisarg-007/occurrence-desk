from __future__ import annotations

import csv
import io


def test_worklist_is_ordered_by_priority_descending(client, analyst_headers):
    items = client.get("/api/v1/reports", headers=analyst_headers).json()["items"]
    priorities = [i["priority"] for i in items]
    assert priorities == sorted(priorities, reverse=True)


def test_keyset_paging_walks_every_row_exactly_once(client, analyst_headers):
    seen: list[int] = []
    cursor = None
    for _ in range(10):  # bounded: a paging bug must fail, not spin
        url = f"/api/v1/reports?page_size=1{f'&cursor={cursor}' if cursor else ''}"
        page = client.get(url, headers=analyst_headers).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert len(seen) == len(set(seen)) == 4


def test_there_is_no_offset_parameter(client, analyst_headers):
    """OFFSET paging is the failure mode the replay finds. It is not in the contract and an
    unknown query parameter must not silently change the result."""
    a = client.get("/api/v1/reports", headers=analyst_headers).json()["items"]
    b = client.get("/api/v1/reports?offset=2", headers=analyst_headers).json()["items"]
    assert a == b


def test_priority_min_filters(client, analyst_headers):
    items = client.get("/api/v1/reports?priority_min=50", headers=analyst_headers).json()["items"]
    assert all(i["priority"] >= 50 for i in items)


def test_malformed_cursor_is_422_not_500(client, analyst_headers):
    r = client.get("/api/v1/reports?cursor=%%%", headers=analyst_headers)
    assert r.status_code == 422


def test_why_reconstructs_the_priority_on_the_row(client, analyst_headers):
    row = client.get("/api/v1/reports", headers=analyst_headers).json()["items"][0]
    why = client.get(f"/api/v1/reports/{row['id']}/why", headers=analyst_headers).json()
    assert why["priority"] == row["priority"]
    assert [t["name"] for t in why["terms"]] == [
        "severity",
        "link_confidence",
        "recency",
        "manager_flag",
    ]
    assert round(100 * sum(t["product"] for t in why["terms"])) == row["priority"]


def test_report_detail_keeps_nasa_paths_verbatim(client, analyst_headers, repo):
    r = repo.report(2)
    r.coded = {"Assessments": {"Primary Problem": "Human Factors"}}
    body = client.get("/api/v1/reports/2", headers=analyst_headers).json()
    assert body["coded"]["Assessments"]["Primary Problem"] == "Human Factors"


def test_analyst_cannot_dispose_of_another_analysts_report(client, analyst_headers, repo):
    repo.report(2).assigned_to = 999
    r = client.post(
        "/api/v1/reports/2/disposition", json={"state": "triaged"}, headers=analyst_headers
    )
    assert r.status_code == 403


def test_export_returns_csv_with_the_documented_columns(client, analyst_headers):
    r = client.get("/api/v1/reports/export", headers=analyst_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == [
        "acn",
        "priority",
        "priority_band",
        "hazard_categories",
        "state",
        "report_date",
        "synopsis",
        "assigned_analyst_id",
    ]
    # Same four fixture reports the in-memory repo seeds in tests (full_sample=False).
    assert len(rows) - 1 == 4


def test_export_respects_priority_min_filter(client, analyst_headers):
    all_rows = list(csv.reader(io.StringIO(
        client.get("/api/v1/reports/export", headers=analyst_headers).text
    )))[1:]
    filtered_rows = list(csv.reader(io.StringIO(
        client.get("/api/v1/reports/export?priority_min=30", headers=analyst_headers).text
    )))[1:]

    assert len(filtered_rows) < len(all_rows)
    assert all(int(row[1]) >= 30 for row in filtered_rows)


def test_export_requires_auth(client):
    r = client.get("/api/v1/reports/export")
    assert r.status_code == 401


def test_disposition_changes_the_state(client, analyst_headers):
    r = client.post(
        "/api/v1/reports/2/disposition",
        json={"state": "escalated", "note": "crossing traffic, TCAS RA"},
        headers=analyst_headers,
    )
    assert r.status_code == 201
    assert client.get("/api/v1/reports/2", headers=analyst_headers).json()["state"] == "escalated"
