"""The console's own surface.

The fragments are the part that is easy to get wrong: they are not in the OpenAPI document, so
nothing else in this suite would notice if one of them served report data to anyone who asked.
"""

from __future__ import annotations

import pytest

FRAGMENTS = ["/console/fragments/worklist", "/console/fragments/report/1"]
PAGES = ["/console", "/console/login", "/console/upload", "/console/reports/1"]


@pytest.mark.parametrize("path", FRAGMENTS)
def test_fragments_require_a_token(client, path):
    """A fragment left open is a data leak that does not look like one, because the page in
    front of it asks for a login."""
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", FRAGMENTS)
def test_fragments_serve_html_to_an_analyst(client, analyst_headers, path):
    r = client.get(path, headers=analyst_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path", PAGES)
def test_page_shells_render_without_a_token(client, path):
    """The shells carry no data - a browser navigation cannot send a bearer token, so the data
    arrives through an authenticated fragment instead."""
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_a_page_shell_leaks_no_report_data(client):
    body = client.get("/console/reports/1").text
    assert "2068539" not in body, "the shell must not embed report content"


def test_worklist_fragment_shows_the_highest_priority_first(client, analyst_headers):
    body = client.get("/console/fragments/worklist", headers=analyst_headers).text
    assert body.index("2068539") < body.index("2059977")


def test_report_fragment_shows_the_four_terms_and_the_score(client, analyst_headers):
    body = client.get("/console/fragments/report/1", headers=analyst_headers).text
    for term in ("severity", "link_confidence", "recency", "manager_flag"):
        assert term in body
    priority = client.get("/api/v1/reports/1", headers=analyst_headers).json()["priority"]
    assert str(priority) in body


def test_report_fragment_is_404_for_an_unknown_report(client, analyst_headers):
    assert (
        client.get("/console/fragments/report/999999", headers=analyst_headers).status_code == 404
    )


def test_worklist_fragment_rejects_a_malformed_cursor_with_422(client, analyst_headers):
    r = client.get("/console/fragments/worklist?cursor=%%%", headers=analyst_headers)
    assert r.status_code == 422


def test_console_pages_are_not_in_the_public_api_document(client):
    """The console is not part of the contract other lanes code against."""
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/console")]
