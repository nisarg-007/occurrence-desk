"""Unit tests for services/worker/parser.py.

Deliberately test the parsing logic against small, synthetic line lists
rather than the real downloaded PDFs: the 30 report-set PDFs are gitignored
(large, and re-downloadable from NASA on demand - see the work-pack, section
0.2), so a test that needs one to exist would fail on a fresh clone or in
CI. Building the exact (page, top, text) triples _parse_one_record expects
lets these tests reproduce specific bugs precisely and run in milliseconds.

Two of these are regression tests for real bugs found by running the parser
against all 30 real report sets, not hypothetical edge cases:
  - a bare "Person" section (single reporter, no number) was silently
    merging into the previous "Aircraft : 2" section
  - a bare "Aircraft" section (single aircraft, no number) was silently
    merging into the previous "Place" section
"""

from __future__ import annotations

import os

import pytest

from services.worker.parser import _parse_one_record as parse_one_record
from services.worker.parser import hazard_code, parse_pdf

NMAC_PDF = "services/worker/sample_pdfs/nmac.pdf"


def lines(*rows: str):
    """Turn a sequence of plain text lines into the (page, top, text) triples
    _parse_one_record expects, one unit of `top` apart."""
    return [(1, float(i), row) for i, row in enumerate(rows)]


def test_hazard_code_slugifies_verbatim_nasa_labels():
    assert hazard_code("Deviation / Discrepancy - Procedural") == "deviation_discrepancy_procedural"
    assert hazard_code("ATC Issue") == "atc_issue"
    assert hazard_code("Conflict") == "conflict"


def test_bare_person_section_does_not_leak_into_aircraft():
    record = parse_one_record(
        lines(
            "ACN: 1000001",
            "Aircraft : 2",
            "Reference : Y",
            "Person",
            "Location Of Person.Aircraft : X",
            "Human Factors : Confusion",
            "Events",
            "Narrative: 1",
            "test narrative",
            "Synopsis",
            "test synopsis",
        ),
        acn="1000001",
        document_id=1,
        page_from=1,
        page_to=1,
    )
    assert record["coded"]["Aircraft : 2"] == {"Reference": "Y"}
    assert record["coded"]["Person"] == {
        "Location Of Person.Aircraft": "X",
        "Human Factors": "Confusion",
    }


def test_bare_aircraft_section_does_not_leak_into_place():
    record = parse_one_record(
        lines(
            "ACN: 1000002",
            "Place",
            "State Reference : VA",
            "Aircraft",
            "Reference : X",
            "Make Model Name : Commercial Fixed Wing",
            "Events",
            "Narrative: 1",
            "test narrative",
            "Synopsis",
            "test synopsis",
        ),
        acn="1000002",
        document_id=1,
        page_from=1,
        page_to=1,
    )
    assert record["coded"]["Place"] == {"State Reference": "VA"}
    assert record["coded"]["Aircraft"] == {
        "Reference": "X",
        "Make Model Name": "Commercial Fixed Wing",
    }


def test_repeated_label_in_one_section_becomes_a_list():
    record = parse_one_record(
        lines(
            "ACN: 1000003",
            "Person",
            "Function.Flight Crew : Pilot Flying",
            "Function.Flight Crew : Single Pilot",
            "Events",
            "Narrative: 1",
            "x",
            "Synopsis",
            "y",
        ),
        acn="1000003",
        document_id=1,
        page_from=1,
        page_to=1,
    )
    assert record["coded"]["Person"]["Function.Flight Crew"] == ["Pilot Flying", "Single Pilot"]
    # but `fields` keeps both as separate (path, value) pairs - that's what
    # report_fields' PRIMARY KEY (report_id, path, value) needs
    pairs = [(f["path"], f["value"]) for f in record["fields"]]
    assert ("Person.Function.Flight Crew", "Pilot Flying") in pairs
    assert ("Person.Function.Flight Crew", "Single Pilot") in pairs


def test_hazards_populated_from_anomaly_fields_deduplicated():
    record = parse_one_record(
        lines(
            "ACN: 1000004",
            "Events",
            "Anomaly.Conflict : NMAC",
            "Anomaly.Deviation / Discrepancy - Procedural : Published Material / Policy",
            "Anomaly.Deviation / Discrepancy - Procedural : FAR",  # same axis, 2nd value
            "Narrative: 1",
            "x",
            "Synopsis",
            "y",
        ),
        acn="1000004",
        document_id=1,
        page_from=1,
        page_to=1,
    )
    codes = sorted(h["code"] for h in record["hazards"])
    assert codes == ["conflict", "deviation_discrepancy_procedural"]  # deduplicated, not 3 rows
    assert all(h["source"] == "nasa" and h["confidence"] == 1.0 for h in record["hazards"])


def test_narrative_and_synopsis_never_mistaken_for_a_new_section():
    # a line inside a narrative that happens to look header-ish (no colon,
    # short) must stay narrative text, not get swallowed as a section change
    record = parse_one_record(
        lines(
            "ACN: 1000005",
            "Events",
            "Narrative: 1",
            "ATC",
            "cleared us direct.",
            "Synopsis",
            "short synopsis",
        ),
        acn="1000005",
        document_id=1,
        page_from=1,
        page_to=1,
    )
    assert record["narrative"] == "ATC cleared us direct."
    assert record["synopsis"] == "short synopsis"


@pytest.mark.skipif(not os.path.exists(NMAC_PDF), reason="sample PDF not downloaded locally")
def test_real_nmac_pdf_yields_fifty_valid_records():
    records = parse_pdf(NMAC_PDF, document_id=1)
    assert len(records) == 50
    assert len({r["acn"] for r in records}) == 50  # every ACN unique
    assert all(r["narrative"] for r in records)
    assert all(r["synopsis"] for r in records)
