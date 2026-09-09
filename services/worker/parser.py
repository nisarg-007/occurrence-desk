"""
Stages 3 + 4: turn one full record's lines into structured data.

Stage 3 = pull out the labelled fields (Date, Place, Aircraft type, etc).
Stage 4 = pull out the narrative (the pilot's own written paragraph) and the
synopsis, separately from the fields.

This file has no "run this" behaviour of its own - see extract_records.py
for that. It just exposes:

    parse_pdf(path, document_id) -> list[dict]

one dict per full record, shaped to match
contracts/extraction-record.schema.json (Stage 5).

Layout notes (confirmed by inspecting the real nmac.pdf, not assumed):
  - This report set is a single column, not side-by-side columns. Each field
    is one line: "<Label> : <Value>". We still build lines from
    extract_words() + x/y position (rather than extract_text()) so this also
    holds up if another of the 30 report sets turns out to lay text out
    differently.
  - A record is bounded by "ACN: <digits>" ... up to (not including) the next
    "ACN: <digits>" that itself starts a full record.
  - Section headers with no value of their own: Time / Day, Place,
    Environment, Component, Events, Assessments. "Aircraft", "Component" and
    "Person" can also appear numbered - "Aircraft : 1", "Person : 2" - when a
    record involves more than one aircraft or person.
  - "Narrative: <n>" opens free prose (one narrative per reporter); "Synopsis"
    opens the closing one-paragraph summary. Both run until the next section
    header, the next narrative/synopsis header, or the end of the record.
"""

import re
from collections import defaultdict

import pdfplumber

ACN_LINE = re.compile(r"^ACN:\s*(\d+)$")
COUNTER_LINE = re.compile(r"^\(\d+\s+of\s+\d+\)$")

BARE_SECTIONS = {"Time / Day", "Place", "Environment", "Aircraft", "Component", "Person", "Events", "Assessments"}
NUMBERED_SECTION_RE = re.compile(r"^(Aircraft|Component|Person)\s*:\s*(\d+)$")
NARRATIVE_RE = re.compile(r"^Narrative:\s*(\d+)$")
SYNOPSIS_LINE = "Synopsis"

# a field line looks like "Label.Path : Value" - split on the first " : "
FIELD_LINE = re.compile(r"^(?P<label>.+?)\s:\s(?P<value>.*)$")

ANOMALY_AXIS_RE = re.compile(r"^Events\.Anomaly\.(.+)$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def hazard_code(label: str) -> str:
    """'Deviation / Discrepancy - Procedural' -> 'deviation_discrepancy_procedural'.

    Matches what Nisarg's ranking/hazard_categories table expects as `code`:
    stable, filesystem/URL-safe, derived from the verbatim NASA axis name so
    it never has to be hand-maintained as new report sets add new axes.
    """
    return _SLUG_RE.sub("_", label.strip().lower()).strip("_")


def _page_lines(page, top_tolerance=2.0):
    """Return [(top, text)] for one page: words grouped into visual lines by
    y-position, then ordered left to right by x-position within each line."""
    words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
    buckets = defaultdict(list)
    for w in words:
        key = round(w["top"] / top_tolerance) * top_tolerance
        buckets[key].append(w)

    lines = []
    for top in sorted(buckets):
        ordered = sorted(buckets[top], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ordered)
        lines.append((top, text))
    return lines


def _find_full_record_starts(all_lines):
    """all_lines: [(page_number, top, text)]. Returns [(acn, line_index)] for
    lines that open a FULL record (ACN line followed by 'Time / Day' within a
    few lines) - as opposed to the front-matter synopsis listing, which is
    ACN followed by 'Synopsis'."""
    starts = []
    for i, (_, _, text) in enumerate(all_lines):
        m = ACN_LINE.match(text.strip())
        if not m:
            continue
        lookahead = [all_lines[j][2].strip() for j in range(i + 1, min(i + 4, len(all_lines)))]
        if "Time / Day" in lookahead:
            starts.append((m.group(1), i))
    return starts


def _parse_one_record(lines, acn, document_id, page_from, page_to):
    """lines: the (page_number, top, text) triples belonging to one record,
    ACN line included. Returns a dict shaped like extraction-record.schema.json."""

    coded = {}          # {section_key: {label: value_or_[values]}}
    flat_fields = []     # [{"path": ..., "value": ...}]
    narrative_parts = []
    synopsis_parts = []

    section = None       # current section key, e.g. "Place" or "Aircraft : 2"
    mode = None          # None | "narrative" | "synopsis"

    def add_field(label, value):
        flat_fields.append({"path": f"{section}.{label}", "value": value})
        bucket = coded.setdefault(section, {})
        if label not in bucket:
            bucket[label] = value
        elif isinstance(bucket[label], list):
            bucket[label].append(value)
        else:
            bucket[label] = [bucket[label], value]

    for _, _, raw in lines:
        text = raw.strip()
        if not text or ACN_LINE.match(text) or COUNTER_LINE.match(text):
            continue

        if text in BARE_SECTIONS:
            section, mode = text, None
            continue

        m = NUMBERED_SECTION_RE.match(text)
        if m:
            section, mode = f"{m.group(1)} : {m.group(2)}", None
            continue

        m = NARRATIVE_RE.match(text)
        if m:
            mode = "narrative"
            continue

        if text == SYNOPSIS_LINE:
            mode = "synopsis"
            continue

        if mode == "narrative":
            narrative_parts.append(raw)
            continue
        if mode == "synopsis":
            synopsis_parts.append(raw)
            continue

        # a field line inside whichever section we're currently in
        m = FIELD_LINE.match(text)
        if m and section:
            add_field(m.group("label"), m.group("value"))
        elif section:
            # a label with no value at all, e.g. "Qualification.Other"
            add_field(text, "")
        # else: a stray line before any section opened - shouldn't happen,
        # dropped rather than guessed at.

    local_time = coded.get("Time / Day", {}).get("Local Time Of Day")

    # NASA's own coding is ground truth - every Anomaly.<axis> field present
    # under Events becomes one 'nasa' hazard row. Deduplicated by axis: the
    # real report_hazards table has PRIMARY KEY (report_id, category_id,
    # source), so an axis mentioned twice with different sub-values (e.g.
    # "Anomaly.Deviation / Discrepancy - Procedural" : "Published Material /
    # Policy" AND : "FAR" on the same record) still contributes one row, not
    # two - the sub-value nuance survives in `fields`, just not here.
    axes = set()
    for f in flat_fields:
        m = ANOMALY_AXIS_RE.match(f["path"])
        if m:
            axes.add(m.group(1))
    hazards = [{"code": hazard_code(axis), "confidence": 1.0, "source": "nasa"} for axis in sorted(axes)]

    return {
        "acn": acn,
        "document_id": document_id,
        "page_from": page_from,
        "page_to": page_to,
        # NASA's "Date" is YYYYMM - month precision only, no day. We do not
        # invent a day to force it into a YYYY-MM-DD date, so this stays
        # null and the raw value survives verbatim in `coded` / `fields`.
        "report_date": None,
        "local_time_of_day": local_time,
        "coded": coded,
        "fields": flat_fields,
        "narrative": " ".join(narrative_parts).strip(),
        "synopsis": " ".join(synopsis_parts).strip() or None,
        # 'nasa' rows only - the model's own predictions (source='model')
        # are a separate, optional step; see services/worker/hazards.py and
        # worker.py, which append them after this function returns.
        "hazards": hazards,
        "parse": {"parser_version": "0.1.0"},
    }


def parse_pdf(path, document_id=1):
    """Parse every full record in one ASRS report-set PDF."""
    with pdfplumber.open(path) as pdf:
        all_lines = []
        for page in pdf.pages:
            for top, text in _page_lines(page):
                all_lines.append((page.page_number, top, text))

        starts = _find_full_record_starts(all_lines)

        records = []
        for idx, (acn, start_idx) in enumerate(starts):
            end_idx = starts[idx + 1][1] if idx + 1 < len(starts) else len(all_lines)
            record_lines = all_lines[start_idx:end_idx]
            page_from = record_lines[0][0]
            page_to = record_lines[-1][0]
            records.append(_parse_one_record(record_lines, acn, document_id, page_from, page_to))

        return records
