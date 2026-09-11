       """
Stage 2: find where each individual report starts and ends inside the PDF.

The report-set PDF actually contains TWO things that both look like a record
boundary:
  1. A "synopsis summary" section near the front - just "ACN: <n>", "(k of 50)",
     then "Synopsis" and one paragraph. This is a table of contents, not a
     full record.
  2. The real full records - "ACN: <n>", "(k of 50)", then "Time / Day" and
     the rest of the coded fields + narrative + synopsis.

We only want #2. A line matching "ACN: <digits>" is treated as the start of a
FULL record only if a "Time / Day" header shows up shortly after it (skipping
past the "(k of 50)" line). This script walks every page, finds those
boundaries, and reports the page range for each of the 50 full records - it
does not extract any fields yet, that's Stage 3.

Run from the repo root:
    python services/worker/find_records.py
"""

import re

import pdfplumber

PDF_PATH = "services/worker/sample_pdfs/nmac.pdf"
ACN_LINE = re.compile(r"^ACN:\s*(\d+)$")


def line_pages(pdf):
    """Yield (page_number, line_text) for every line in the document, in order."""
    for page in pdf.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            yield page.page_number, line


def find_full_record_starts(pdf):
    """Return a list of (acn, page_number) for lines that start a FULL record."""
    lines = list(line_pages(pdf))
    starts = []
    for i, (page_num, line) in enumerate(lines):
        m = ACN_LINE.match(line.strip())
        if not m:
            continue
        # look at the next few lines (skipping the "(k of 50)" counter) for
        # the header that tells us whether this is a full record
        lookahead = [lines[j][1].strip() for j in range(i + 1, min(i + 4, len(lines)))]
        if "Time / Day" in lookahead:
            starts.append((m.group(1), page_num))
    return starts


with pdfplumber.open(PDF_PATH) as pdf:
    starts = find_full_record_starts(pdf)

    print(f"Full records found: {len(starts)} (expected 50)")
    print("\nFirst 5:")
    for acn, page in starts[:5]:
        print(f"  ACN {acn}  starts on page {page}")
    print("\nLast 5:")
    for acn, page in starts[-5:]:
        print(f"  ACN {acn}  starts on page {page}")

    # page range for each record: from its start page to (next record's start
    # page - 1), or the last page of the document for the final record
    print("\nPage ranges for the first 3 records:")
    for idx in range(3):
        acn, start_page = starts[idx]
        end_page = (starts[idx + 1][1] - 1) if idx + 1 < len(starts) else len(pdf.pages)
        print(f"  ACN {acn}: pages {start_page}-{end_page}")
