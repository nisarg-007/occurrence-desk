"""The console's own surface.

The fragments are the part that is easy to get wrong: they are not in the OpenAPI document, so
nothing else in this suite would notice if one of them served report data to anyone who asked.
"""

from __future__ import annotations

import pytest

FRAGMENTS = [
    "/console/fragments/worklist",
    "/console/fragments/report/1",
    "/console/fragments/stats",
    "/console/fragments/dashboard",
]
PAGES = [
    "/console",
    "/console/login",
    "/console/upload",
    "/console/reports/1",
    "/console/dashboard",
]


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
    """ACN 2068539 (a real NASA NMAC report, severity 0.95) outranks ACN 2105330 (a real ATC
    staffing complaint, severity 0.50) - computed from the ranking formula, not hand-set."""
    body = client.get("/console/fragments/worklist", headers=analyst_headers).text
    assert body.index("2068539") < body.index("2105330")


def test_report_fragment_shows_the_four_terms_and_the_score(client, analyst_headers):
    """Term names are shown as words, not as the API's snake_case field names - the
    analyst is not reading a JSON payload."""
    body = client.get("/console/fragments/report/1", headers=analyst_headers).text
    for term in ("Severity", "Link confidence", "Recency", "Manager flag"):
        assert term in body, f"{term} missing from the breakdown"
    priority = client.get("/api/v1/reports/1", headers=analyst_headers).json()["priority"]
    assert str(priority) in body


def test_severity_is_never_communicated_by_colour_alone(client, analyst_headers):
    """A band name in text plus a four-step meter, so the ranking survives colour
    blindness, a greyscale printout, and a screen reader.

    The band checked here is "high", not "critical": with real, honestly-unlinked ASRS
    reports (no fabricated link confidence) and real report ages, nothing in the small
    fixture clears the 70-point critical floor - see docs/measurements.md. That is the
    formula behaving correctly on real numbers, not a gap in the fixture.
    """
    body = client.get("/console/fragments/worklist", headers=analyst_headers).text
    assert 'data-level="high"' in body
    assert "High" in body
    assert '<span class="meter"' in body


def test_worklist_rows_link_to_the_console_not_the_raw_api(client, analyst_headers):
    body = client.get("/console/fragments/worklist", headers=analyst_headers).text
    assert "/console/reports/" in body
    assert 'href="/api/v1/reports/' not in body


def test_stats_fragment_hides_queue_tiles_from_an_analyst(client, analyst_headers, manager_headers):
    """Queue depth is manager-only. An analyst sees a shorter strip, not an empty box
    where a permission used to be."""
    a = client.get("/console/fragments/stats", headers=analyst_headers)
    m = client.get("/console/fragments/stats", headers=manager_headers)
    assert a.status_code == m.status_code == 200
    assert "Waiting to parse" not in a.text
    assert "Waiting to parse" in m.text


def test_the_console_does_not_show_sql_to_an_analyst(client):
    """The worklist page used to open with `priority DESC, report_date DESC, id DESC`.
    That is a note to the team, not information for the person doing the triage."""
    body = client.get("/console").text
    assert "DESC" not in body


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


def test_dashboard_fragment_shows_the_stub_banner(client, analyst_headers):
    """The test client always runs against InMemoryRepo, so is_stub is always true here -
    the banner must say so in words, not just imply it with a colour. It also has to say
    the data is real, not synthetic - that's the whole point of the banner now."""
    body = client.get("/console/fragments/dashboard", headers=analyst_headers).text
    assert "Real ASRS reports" in body
    assert "asrs.arc.nasa.gov" in body


def test_dashboard_fragment_charts_are_never_colour_alone(client, analyst_headers):
    """Every chart is `role="img"` with an `aria-label` stating the real numbers, and the
    priority-band chart also ships a text table fallback - a screen reader gets the same
    information a sighted reader gets from the bars."""
    body = client.get("/console/fragments/dashboard", headers=analyst_headers).text
    assert body.count('role="img"') >= 3
    assert "Reports by priority band" in body
    assert "<table" in body


def test_dashboard_page_shell_leaks_no_report_data(client):
    """Same rule as the report page: the shell carries no data, only the authenticated
    fragment does - a browser navigation cannot send a bearer token."""
    body = client.get("/console/dashboard").text
    assert 'role="img"' not in body


def test_dev_session_mints_a_working_manager_token_locally(client):
    """The local-only auto-sign-in endpoint hands out a token that is real, not a stub -
    it works against an actual manager-only route."""
    r = client.get("/console/dev-session")
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "manager"
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/console/fragments/stats", headers=headers).status_code == 200


def test_dev_session_is_404_outside_a_local_build(client):
    """Auth itself is not touched by this endpoint - it only exists at all when
    APP_ENV=local, so a deployed build cannot mint a session by asking nicely."""
    from services.api.deps import settings as settings_dep
    from services.api.main import app
    from services.common.settings import Settings

    app.dependency_overrides[settings_dep] = lambda: Settings(app_env="production")
    try:
        assert client.get("/console/dev-session").status_code == 404
    finally:
        app.dependency_overrides.pop(settings_dep, None)
