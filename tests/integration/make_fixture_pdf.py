"""
Build a small PDF laid out the way an ASRS report-set PDF is, so the SQL path
can be exercised without a network download.

This is NOT a substitute for the real corpus. The 30 report-set PDFs are
gitignored (work-pack §0.2) and the extraction accuracy number in Smit's lane
must be measured against those, not against this. What this fixture proves is
narrower and still worth proving: that parser output flows into Parva's tables
and back out through Nisarg's API, with the idempotency constraints holding.

Usage:
    python tests/integration/make_fixture_pdf.py /tmp/fixture.pdf
"""

from __future__ import annotations

import sys

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

#: Two records, so the ACN record-boundary split has something to split on.
#: The field labels are the verbatim dotted paths from the real corpus.
RECORDS = [
    [
        "ACN: 9000001",
        "(1 of 2)",
        "Time / Day",
        "Date : 202212",
        "Local Time Of Day : 1201-1800",
        "Place",
        "Locale Reference.ATC Facility : ZZZ.TRACON",
        "State Reference : US",
        "Altitude.MSL.Single Value : 8000",
        "Environment",
        "Flight Conditions : VMC",
        "Light : Daylight",
        "Aircraft : 1",
        "Make Model Name : B737 Next Generation Undifferentiated",
        "Aircraft Operator : Air Carrier",
        "Flight Phase : Climb",
        "Person : 1",
        "Reporter Organization : Air Carrier",
        "Function.Flight Crew : Captain",
        "Events",
        "Anomaly.Deviation - Altitude : Overshoot",
        "Anomaly.ATC Issue : All Types",
        "Detector.Person : Flight Crew",
        "Assessments",
        "Primary Problem : Human Factors",
        "Narrative: 1",
        "During a climb out of a busy terminal area we were issued a level off "
        "and the altitude was overshot by approximately two hundred feet before "
        "the autopilot captured. ATC queried the altitude and we reported the "
        "deviation immediately. Workload and a late frequency change contributed.",
        "Synopsis",
        "Air carrier crew reported an altitude overshoot during climb after a late "
        "level off clearance.",
    ],
    [
        "ACN: 9000002",
        "(2 of 2)",
        "Time / Day",
        "Date : 202212",
        "Local Time Of Day : 0601-1200",
        "Place",
        "Locale Reference.Airport : ZZZ.Airport",
        "State Reference : US",
        "Environment",
        "Flight Conditions : IMC",
        "Aircraft : 1",
        "Make Model Name : A320",
        "Aircraft Operator : Air Carrier",
        "Flight Phase : Taxi",
        "Person : 1",
        "Reporter Organization : Air Carrier",
        "Function.Flight Crew : First Officer",
        "Events",
        "Anomaly.Ground Incursion : Taxiway",
        "Detector.Person : Ground Personnel",
        "Assessments",
        "Primary Problem : Ambiguous",
        "Narrative: 1",
        "While taxiing in low visibility we crossed a hold short line before "
        "receiving clearance. Ground personnel called our attention to the "
        "position and we stopped immediately. Signage was partially obscured.",
        "Synopsis",
        "Air carrier crew reported crossing a hold short line while taxiing in low "
        "visibility conditions.",
    ],
]


def build(path: str) -> str:
    pdf = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    for record in RECORDS:
        pdf.setFont("Helvetica", 9)
        y = height - 54
        for line in record:
            # wrap long prose so the narrative spans several lines the way it
            # really does, instead of one impossibly wide line
            for chunk in _wrap(line, 105):
                if y < 54:
                    pdf.showPage()
                    pdf.setFont("Helvetica", 9)
                    y = height - 54
                pdf.drawString(54, y, chunk)
                y -= 12
        pdf.showPage()
    pdf.save()
    return path


def _wrap(text: str, width: int) -> list[str]:
    if len(text) <= width:
        return [text]
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fixture.pdf"))
