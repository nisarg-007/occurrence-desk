"""The storage seam.

Parva owns `db/models.py` and the migrations; they land in week 2. Until then the API is
developed and tested against `InMemoryRepo`, which implements the same Protocol. This is the
"generate a stub server from the contract and check it in" step from the work pack - everyone
else builds against a running API from week 1 instead of waiting on the schema.

When the SQLAlchemy models land, `SqlRepo` implements this Protocol and one line in deps.py
changes. No route changes.
"""

from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass, field
from typing import Protocol

from services.api import ranking
from services.api.pagination import Cursor, sort_key
from services.api.security import hash_password


@dataclass
class UserRow:
    id: int
    email: str
    password_hash: str
    role: str
    is_active: bool = True


@dataclass
class DocumentRow:
    id: int
    sha256: str
    s3_bucket: str
    s3_key: str
    original_filename: str | None
    byte_size: int | None
    uploaded_by: int
    uploaded_at: dt.datetime
    status: str = "received"
    attempts: int = 0
    error_text: str | None = None
    page_count: int | None = None


@dataclass
class ReportRow:
    id: int
    document_id: int
    acn: str
    report_date: dt.date | None
    synopsis: str | None
    narrative: str
    coded: dict = field(default_factory=dict)
    severity_weights: tuple[float, ...] = ()
    hazards: list[dict] = field(default_factory=list)
    best_link_confidence: float | None = None
    linked_flight: dict | None = None
    manager_flagged: bool = False
    state: str = "new"
    assigned_to: int | None = None


def _rec(
    acn: str,
    ym: tuple[int, int],
    synopsis: str,
    narrative: str,
    sev: float,
    code: str,
    label: str,
    *,
    place: str,
    aircraft: str,
    primary: str,
    report_set: str,
    url: str,
) -> dict:
    """One real NASA ASRS record. `ym` is (year, month) - the source page gives a month, not
    a day, so the 1st is not implied as fact; the 15th is used as a neutral mid-month stand-in
    so `report_date` is a valid date without asserting a day nobody told us."""
    year, month = ym
    return dict(
        acn=acn,
        report_date=dt.date(year, month, 15),
        synopsis=synopsis,
        narrative=narrative,
        sev=sev,
        code=code,
        label=label,
        coded={
            "Source": {
                "NASA report set": report_set,
                "Source URL": url,
                "Data note": (
                    "Synopsis is verbatim; narrative is an excerpt captured by an automated "
                    "fetch this session, not Smit's byte-exact pdfplumber parser - the full "
                    "narrative and NASA's complete coded field tree are that lane's job. "
                    "Not linked to a real flight - that's Parva's join, not done here."
                ),
            },
            "Assessments": {"Primary Problem": primary},
            "Aircraft": {"Description": aircraft},
            "Place": {"Location": place},
        },
    )


#: Real NASA ASRS incidents, fetched from the actual report-set PDFs at
#: asrs.arc.nasa.gov this session - not generated. Every ACN, synopsis and narrative
#: excerpt below traces to a real, citable source (see each record's `coded["Source"]`).
#: Severity anchors one per hazard category, chosen to match the category's real-world
#: gravity (a near-midair collision outweighs an ATC staffing complaint); only categories
#: we actually fetched real examples for are represented - no invented category filled a gap.
#: First four are the ranking-order-sensitive fixture used when demo_rows=0 (tests); the
#: rest only appear in a live run. `best_link_confidence` is left unset throughout - no BTS
#: join has been run against any of these, and a fabricated confidence would be exactly the
#: kind of invented number this dataset exists to avoid.
_REAL_ASRS_SAMPLE: tuple[dict, ...] = (
    _rec(
        "2068539",
        (2024, 1),
        "Experimental aircraft pilot operating in ZMA airspace reported a NMAC with another "
        "VFR aircraft traveling in the opposite direction at the same altitude.",
        "Encountered opposite-direction VFR traffic at identical altitude near FORNI "
        "intersection. Received an ADS-B traffic alert and executed immediate evasive "
        "action, estimating 300-400 ft final separation. Criticized local Letters of "
        "Agreement that allegedly assign VFR aircraft opposite altitudes from standard "
        "practice, creating collision risk.",
        0.95,
        "conflict_nmac",
        "Conflict",
        place="ZJX ARTCC, Florida, 7,500 ft MSL",
        aircraft="Experimental/homebuilt (VFR) vs. small aircraft (VFR)",
        primary="Airspace Structure / Procedure",
        report_set="Near Midair Collision (NMAC) Incidents",
        url="https://asrs.arc.nasa.gov/docs/rpsts/nmac.pdf",
    ),
    _rec(
        "2093064",
        (2024, 3),
        "Air carrier Captain reported a lack of indication of whether the ILS critical "
        "holding point was in use at FACT airport.",
        "The Controller monitors Clearance Delivery, Ground and Tower calls. We were "
        "cleared to taxi on A1, cross Runway 16 to Taxiway A2 holding point for Runway 19.",
        0.90,
        "runway_incursion",
        "Ground Incursion",
        place="FACT Airport (Cape Town)",
        aircraft="Widebody transport",
        primary="Procedure",
        report_set="Runway Incursions",
        url="https://asrs.arc.nasa.gov/docs/rpsts/rwy_incur.pdf",
    ),
    _rec(
        "2096810",
        (2024, 3),
        "B737 MAX 8 flight crew reported they failed to make a crossing restriction on "
        "arrival into ATL after encountering wake turbulence from the preceding aircraft.",
        "We were flying the GLAVN 1 Arrival landing west at ATL. Center cleared us to "
        "cross GLAVN at 14,000 ft and we were sequenced behind another airliner "
        "approximately 5-7 NM in front of us. While passing through 16,000 ft, we "
        "encountered wake turbulence and the aircraft rolled left/right and shook with "
        "moderate force.",
        0.60,
        "altitude_deviation",
        "Deviation - Altitude",
        place="ZTL ARTCC, Georgia",
        aircraft="B737 MAX 8",
        primary="Ambiguous",
        report_set="Altitude Deviations",
        url="https://asrs.arc.nasa.gov/docs/rpsts/altdev.pdf",
    ),
    _rec(
        "2105330",
        (2024, 4),
        "ZAB Controller reported the complexity and workload levels at sectors were "
        "unsafe due to scheduled GPS jamming causing navigational errors and frequency "
        "congestion.",
        "We had weather today with a high volume workload due to additional weather in "
        "the Houston metro. Starting at XA30, GPS jamming from White Sands started and "
        "immediately aircraft started to take over the frequencies and talk about "
        "losing their ADSB and transponders.",
        0.50,
        "atc_issue",
        "ATC Issue",
        place="ZAB ARTCC, New Mexico",
        aircraft="(controller report - no single aircraft)",
        primary="Company Policy",
        report_set="Air Traffic Controller Reports",
        url="https://asrs.arc.nasa.gov/docs/rpsts/ctlr.pdf",
    ),
    _rec(
        "2063011",
        (2023, 12),
        "General aviation pilot reported a NMAC in the traffic pattern resulting from "
        "failure to follow traffic as instructed by ATC.",
        "A tower gave ambiguous traffic advisories during busy operations. Missed "
        "portions of the transmission and reported 'traffic in sight' without actually "
        "acquiring the correct aircraft. Upon turning base, observed a Cessna crossing "
        "below at several hundred feet, necessitating extended downwind to separate.",
        0.95,
        "conflict_nmac",
        "Conflict",
        place="ZZZ Airport (Class D), 2,300 ft MSL",
        aircraft="SR20 vs. Cessna, both on final approach",
        primary="Human Factors",
        report_set="Near Midair Collision (NMAC) Incidents",
        url="https://asrs.arc.nasa.gov/docs/rpsts/nmac.pdf",
    ),
    _rec(
        "2063005",
        (2023, 12),
        "A student pilot reported experiencing several events during a flight training "
        "session that they believe were unsatisfactory and unsafe on the part of their "
        "flight instructor.",
        "During ground reference maneuvers, the flight instructor remained in proximity "
        "to another aircraft despite the student's safety concerns and lack of radio "
        "contact. When the other aircraft passed 300 feet overhead, the instructor "
        "dismissed the danger as intentional training.",
        0.95,
        "conflict_nmac",
        "Conflict",
        place="ZZZ ARTCC airspace, 2,200 ft MSL",
        aircraft="Skyhawk 172 (training) vs. unknown aircraft (training)",
        primary="Human Factors",
        report_set="Near Midair Collision (NMAC) Incidents",
        url="https://asrs.arc.nasa.gov/docs/rpsts/nmac.pdf",
    ),
    _rec(
        "2102174",
        (2024, 3),
        "B737 MAX 8 Captain reported a distracting high pitched tone on descent that led "
        "to being high on a fix. With the help of Maintenance, the Reporter discovered "
        "the problem may be caused by the ground crew's unsafe plug removal procedure.",
        "After being cleared direct to ZZZZZ on the arrival and cross it at 11,000 ft, "
        "we encountered a high pitch tone that had been building up after departing ZZZ. "
        "Due to the high pitch tone encounter and late crossing restriction clearance, "
        "we arrived at the fix a little high.",
        0.60,
        "altitude_deviation",
        "Deviation - Altitude",
        place="ZZZ Airport",
        aircraft="B737 MAX 8",
        primary="Aircraft",
        report_set="Altitude Deviations",
        url="https://asrs.arc.nasa.gov/docs/rpsts/altdev.pdf",
    ),
    _rec(
        "2096120",
        (2024, 3),
        "ARTCC Controller reported an aircraft flying in icing and snow conditions was "
        "unable to climb above MVA resulting in a CFTT event.",
        "Aircraft X came into my sector at 10,000 ft. They were on an IFR flight plan "
        "heading to ZZZ1. 10,000 is fairly low for the terrain in the area and routing "
        "was going to be needed for Aircraft X to stay at 10,000.",
        0.60,
        "altitude_deviation",
        "Deviation - Altitude",
        place="ZZZ ARTCC",
        aircraft="Bonanza 36",
        primary="Weather",
        report_set="Altitude Deviations",
        url="https://asrs.arc.nasa.gov/docs/rpsts/altdev.pdf",
    ),
    _rec(
        "2095743",
        (2024, 3),
        "PC12 pilot reported receiving altitude warning during descent. Pilot corrected "
        "altitude and continued uneventfully.",
        "The decision to return to base was made enroute from ZZZ to ZZZ1 due to "
        "unforecast weather conditions to ZZZ1 airport. We had just climbed through some "
        "cumulus clouds and picked up some light rime ice at 5,000 ft.",
        0.60,
        "altitude_deviation",
        "Deviation - Altitude",
        place="ZZZ TRACON",
        aircraft="PC-12",
        primary="Human Factors",
        report_set="Altitude Deviations",
        url="https://asrs.arc.nasa.gov/docs/rpsts/altdev.pdf",
    ),
    _rec(
        "2089579",
        (2024, 2),
        "Light aircraft pilot reported landing and while slowing down for a turnoff at "
        "Bravo 1 taxiway at SMO, both main tires ended up going flat.",
        "I landed on Runway 21 at SMO. ATIS was reporting the winds as calm. After an "
        "uneventful touchdown, I applied the brakes to slow to exit at Bravo 1.",
        0.90,
        "runway_incursion",
        "Ground Incursion",
        place="SMO Airport (Santa Monica)",
        aircraft="Small aircraft",
        primary="Aircraft",
        report_set="Runway Incursions",
        url="https://asrs.arc.nasa.gov/docs/rpsts/rwy_incur.pdf",
    ),
    _rec(
        "2084287",
        (2024, 2),
        "TRACON and Tower Controllers reported traffic landed on closed parallel runway "
        "at night, without a clearance. Controllers reported that the lit X closure "
        "indicator was not in place.",
        "Aircraft X was cleared to land on runway XXL, but landed without receiving a "
        "landing clearance on a closed runway while personnel and equipment were "
        "occupying the departure end.",
        0.90,
        "runway_incursion",
        "Ground Incursion",
        place="ZZZ Airport",
        aircraft="Skyhawk 172 / Cutlass 172",
        primary="Airport",
        report_set="Runway Incursions",
        url="https://asrs.arc.nasa.gov/docs/rpsts/rwy_incur.pdf",
    ),
    _rec(
        "2081184",
        (2024, 1),
        "Tower Ground Controller reported a taxiing aircraft began to stray from its "
        "clearance and caused a critical ground conflict with a landing aircraft. The "
        "Controller states there were several calls to the wayward aircraft before "
        "contact was made.",
        "I taxied Aircraft X from FBO to Runway XXR for departure via taxiway 1 "
        "initially, to hold short of Runway YY. After receiving permission from Local "
        "Control 2 I continued their taxi with a left on Runway YY.",
        0.90,
        "runway_incursion",
        "Ground Incursion",
        place="ZZZ Airport",
        aircraft="Military (Aircraft 1); small transport, 2 turbojet (Aircraft 2)",
        primary="Human Factors",
        report_set="Runway Incursions",
        url="https://asrs.arc.nasa.gov/docs/rpsts/rwy_incur.pdf",
    ),
    _rec(
        "2085398",
        (2024, 2),
        "A300 flight crew reported loss of aircraft control and autopilot disconnect "
        "while flying through severe turbulence during cruise descent. Flight crew "
        "regained control and continued flight.",
        "While navigating direct ZZZ from ZZZZZ1 at FL300, ATC ZZZ Center notified us, "
        "Aircraft X, of two areas of convective activity along our route of flight to "
        "ZZZ. Encountered severe turbulence for approximately 30 seconds while "
        "descending through FL295 until FL285.",
        0.40,
        "weather",
        "Inflight Weather Encounter",
        place="ZZZ ARTCC, FL300",
        aircraft="A300",
        primary="Weather",
        report_set="Inflight Weather Encounters",
        url="https://asrs.arc.nasa.gov/docs/rpsts/wx.pdf",
    ),
    _rec(
        "2085091",
        (2024, 2),
        "General aviation pilot reported they failed to extend the landing gear "
        "resulting in a gear up landing.",
        "Due to the gusty winds, I opted for a flaps 20 approach and landing. Became "
        "distracted with ATC communications and somehow missed landing gear extension. "
        "I allowed myself to deviate from the number one priority - fly the airplane.",
        0.40,
        "weather",
        "Inflight Weather Encounter",
        place="ZZZ Airport, 9 ft MSL",
        aircraft="Small aircraft, high wing, 1 engine, retractable gear",
        primary="Human Factors",
        report_set="Inflight Weather Encounters",
        url="https://asrs.arc.nasa.gov/docs/rpsts/wx.pdf",
    ),
    _rec(
        "2085028",
        (2024, 2),
        "Flight Instructor with student reported a NMAC while maneuvering in a practice "
        "area. Flight Instructor took evasive action to avoid a collision.",
        "A near mid-air collision situation occurred. As the student began the turn, "
        "they spotted nearby traffic to the southeast. The SkyWatch system alerted us "
        "to the presence of same-altitude traffic. I assumed control from the student "
        "and expedited the turn and climb away from the other aircraft.",
        0.40,
        "weather",
        "Inflight Weather Encounter",
        place="170 degrees, 11 NM, 5,500 ft MSL",
        aircraft="Two small aircraft",
        primary="Human Factors",
        report_set="Inflight Weather Encounters",
        url="https://asrs.arc.nasa.gov/docs/rpsts/wx.pdf",
    ),
    _rec(
        "2084189",
        (2024, 1),
        "EMB-145 Captain reported entering an area of severe turbulence resulting in "
        "course and altitude deviations. The Captain regained control of the aircraft "
        "when the turbulence stopped, and they continued safely to destination.",
        "We encountered severe turbulence. The aircraft was thrown down about 400 feet "
        "instantly with about twenty degrees of bank to the left. After about a minute, "
        "the turbulence subsided to light turbulence and we proceeded to climb back to "
        "our assigned altitude.",
        0.40,
        "weather",
        "Inflight Weather Encounter",
        place="13,000 ft MSL",
        aircraft="EMB ERJ 145 ER/LR",
        primary="Weather",
        report_set="Inflight Weather Encounters",
        url="https://asrs.arc.nasa.gov/docs/rpsts/wx.pdf",
    ),
    _rec(
        "2105322",
        (2024, 4),
        "A TRACON Controller reported they could not provide adequate assistance to a "
        "small aircraft requesting priority handling due to workload of working "
        "combined sectors because of chronic lack of staffing issues at their facility.",
        "We have been short staffed for too many years and it's creating so many unsafe "
        "situations. The FAA has created an unsafe environment to work and for the "
        "flying public.",
        0.50,
        "atc_issue",
        "ATC Issue",
        place="SCT TRACON, California",
        aircraft="Small aircraft, high wing, 1 engine",
        primary="Staffing",
        report_set="Air Traffic Controller Reports",
        url="https://asrs.arc.nasa.gov/docs/rpsts/ctlr.pdf",
    ),
    _rec(
        "2103770",
        (2024, 4),
        "A TRACON Controller reported Tower allowed aircraft to depart opposite "
        "direction into arrival traffic due to confusion during a runway configuration "
        "change.",
        "In the process of changing flows from south to north flow, Tower put the two "
        "aircraft on my frequency climbing via and on the SID. I had to turn both "
        "aircraft immediately to avoid a midair collision.",
        0.50,
        "atc_issue",
        "ATC Issue",
        place="D21 TRACON, Michigan",
        aircraft="Two unlisted aircraft",
        primary="Procedure",
        report_set="Air Traffic Controller Reports",
        url="https://asrs.arc.nasa.gov/docs/rpsts/ctlr.pdf",
    ),
    _rec(
        "2103769",
        (2024, 4),
        "ZAU Controller reported IND Tower and SBN TRACON use the same UHF Frequency of "
        "257.8 which caused confusion when the controller attempted to issue frequency "
        "change.",
        "Aircraft X was requesting UHF frequency for SBN. We shipped aircraft to SBN "
        "Approach on 257.8 and aircraft came back and told us the people on 257.8 told "
        "them it's the wrong frequency.",
        0.50,
        "atc_issue",
        "ATC Issue",
        place="ZAU ARTCC, Illinois",
        aircraft="Medium large transport (military)",
        primary="ATC Equipment / Nav Facility / Buildings",
        report_set="Air Traffic Controller Reports",
        url="https://asrs.arc.nasa.gov/docs/rpsts/ctlr.pdf",
    ),
)


class Repository(Protocol):
    def user_by_email(self, email: str) -> UserRow | None: ...
    def document_by_sha(self, sha256: str) -> DocumentRow | None: ...
    def create_document(self, **kw) -> DocumentRow: ...
    def document(self, document_id: int) -> DocumentRow | None: ...
    def mark_queued(self, document_id: int) -> bool: ...
    def unmark_queued(self, document_id: int) -> None: ...
    def reports_for_document(self, document_id: int) -> list[ReportRow]: ...
    def report(self, report_id: int) -> ReportRow | None: ...
    def list_reports(
        self, *, cursor: Cursor | None, page_size: int, **filters
    ) -> list[ReportRow]: ...
    def add_disposition(self, report_id: int, analyst_id: int, **kw) -> dict: ...
    def assign(
        self, report_id: int, analyst_id: int, manager_flagged: bool
    ) -> ReportRow | None: ...
    def parsed_in_last_60s(self) -> int: ...


class InMemoryRepo:
    """M1 stub. Deliberately small and honest: it is not a database and does not pretend to be."""

    #: True while the API is serving the in-memory stub rather than a database. The console
    #: shows this on screen: numbers on a dashboard must never be mistaken for real results.
    is_stub = True

    def __init__(self, seed: bool = True, demo_rows: int = 140) -> None:
        self.users: dict[str, UserRow] = {}
        self.documents: dict[int, DocumentRow] = {}
        self.reports: dict[int, ReportRow] = {}
        self.dispositions: list[dict] = []
        # One counter per table, like BIGSERIAL - so a report id is not silently a user id.
        self._ids: dict[str, itertools.count] = {
            t: itertools.count(1) for t in ("users", "documents", "reports", "dispositions")
        }
        self._parsed_at: list[dt.datetime] = []
        self.demo_rows = demo_rows
        if seed:
            self._seed()

    # -- helpers ---------------------------------------------------------------
    def _next(self, table: str) -> int:
        return next(self._ids[table])

    def _seed(self) -> None:
        # Local development logins only. The real seed script guards on ENV != 'prod'
        # in the script itself, not just in a comment.
        pw = hash_password("occdesk-local")
        for email, role in (
            ("analyst@occdesk.example", "analyst"),
            ("manager@occdesk.example", "manager"),
            ("admin@occdesk.example", "admin"),
        ):
            uid = self._next("users")
            self.users[email] = UserRow(uid, email, pw, role)

        today = dt.date.today()
        doc_id = self._next("documents")
        self.documents[doc_id] = DocumentRow(
            id=doc_id,
            sha256="0" * 64,
            s3_bucket="occdesk-dev-docs",
            s3_key=f"raw/{today:%Y/%m/%d}/{'0' * 64}.pdf",
            original_filename="asrs-report-sets.pdf",
            byte_size=1_843_200,
            uploaded_by=1,
            uploaded_at=dt.datetime.now(dt.UTC),
            status="parsed",
            page_count=112,
        )
        # demo_rows=0 (tests) gets the first four - one per hazard category, chosen so the
        # ranking spread is visible - rather than the whole batch, so the fixture stays small
        # and fast. A real deployment gets all of them.
        records = _REAL_ASRS_SAMPLE if self.demo_rows else _REAL_ASRS_SAMPLE[:4]
        for rec in records:
            self._add_report(doc_id, **rec)

    def _add_report(
        self,
        doc_id: int,
        *,
        acn: str,
        report_date: dt.date,
        synopsis: str,
        narrative: str,
        sev: float,
        code: str,
        label: str,
        coded: dict | None = None,
        link: float = 0.0,
    ) -> int:
        rid = self._next("reports")
        self.reports[rid] = ReportRow(
            id=rid,
            document_id=doc_id,
            acn=acn,
            report_date=report_date,
            synopsis=synopsis,
            narrative=narrative,
            coded=coded or {},
            severity_weights=(sev,),
            hazards=[{"code": code, "label": label, "confidence": 1.0, "source": "nasa"}],
            best_link_confidence=link or None,
        )
        return rid

    def priority(self, r: ReportRow, today: dt.date | None = None) -> int:
        return ranking.priority(
            ranking.ScoreInput(
                severity_weights=r.severity_weights,
                best_link_confidence=r.best_link_confidence,
                report_date=r.report_date,
                manager_flagged=r.manager_flagged,
            ),
            today or dt.date.today(),
        )

    # -- Repository ------------------------------------------------------------
    def user_by_email(self, email: str) -> UserRow | None:
        return self.users.get(email.lower())

    def document_by_sha(self, sha256: str) -> DocumentRow | None:
        return next((d for d in self.documents.values() if d.sha256 == sha256), None)

    def create_document(self, **kw) -> DocumentRow:
        # Mirrors the `documents.sha256` unique constraint: the same PDF is one row.
        existing = self.document_by_sha(kw["sha256"])
        if existing:
            return existing
        did = self._next("documents")
        row = DocumentRow(id=did, uploaded_at=dt.datetime.now(dt.UTC), **kw)
        self.documents[did] = row
        return row

    def document(self, document_id: int) -> DocumentRow | None:
        return self.documents.get(document_id)

    def mark_queued(self, document_id: int) -> bool:
        """True when this call is the one that enqueued it. Second call returns False, still 202."""
        d = self.documents.get(document_id)
        if d is None or d.status != "received":
            return False
        d.status = "queued"
        return True

    def unmark_queued(self, document_id: int) -> None:
        """Put a document back to 'received' after the enqueue failed.

        Without this, a failed SendMessage leaves a row saying 'queued' that no message exists
        for - a document stuck forever, which is exactly the silent loss our success criteria
        forbid. Rolling back means the next submit can enqueue it.
        """
        d = self.documents.get(document_id)
        if d is not None and d.status == "queued":
            d.status = "received"

    def reports_for_document(self, document_id: int) -> list[ReportRow]:
        return [r for r in self.reports.values() if r.document_id == document_id]

    def report(self, report_id: int) -> ReportRow | None:
        return self.reports.get(report_id)

    def list_reports(
        self,
        *,
        cursor: Cursor | None = None,
        page_size: int = 50,
        category: str | None = None,
        state: str | None = None,
        priority_min: int | None = None,
        q: str | None = None,
    ) -> list[ReportRow]:
        today = dt.date.today()
        rows = list(self.reports.values())
        if category:
            rows = [r for r in rows if any(h["code"] == category for h in r.hazards)]
        if state:
            rows = [r for r in rows if r.state == state]
        if priority_min is not None:
            rows = [r for r in rows if self.priority(r, today) >= priority_min]
        if q:
            needle = q.lower()
            rows = [
                r
                for r in rows
                if needle in r.narrative.lower() or needle in (r.synopsis or "").lower()
            ]
        rows.sort(key=lambda r: sort_key(self.priority(r, today), r.report_date, r.id))
        if cursor is not None:
            anchor = sort_key(cursor.priority, cursor.report_date, cursor.report_id)
            rows = [
                r for r in rows if sort_key(self.priority(r, today), r.report_date, r.id) > anchor
            ]
        return rows[: page_size + 1]  # one extra row tells the caller whether more exist

    def add_disposition(self, report_id: int, analyst_id: int, **kw) -> dict:
        row = {
            "id": self._next("dispositions"),
            "report_id": report_id,
            "analyst_id": analyst_id,
            "created_at": dt.datetime.now(dt.UTC),
            **kw,
        }
        self.dispositions.append(row)
        r = self.reports.get(report_id)
        if r is not None and kw.get("state"):
            r.state = kw["state"]
        return row

    def assign(self, report_id: int, analyst_id: int, manager_flagged: bool) -> ReportRow | None:
        r = self.reports.get(report_id)
        if r is None:
            return None
        r.assigned_to = analyst_id
        r.manager_flagged = manager_flagged
        return r

    def parsed_in_last_60s(self) -> int:
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=60)
        self._parsed_at = [t for t in self._parsed_at if t >= cutoff]
        return len(self._parsed_at)
