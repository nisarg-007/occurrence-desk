"""Seeds `hazard_categories` — the taxonomy `report_hazards` and Nisarg's ranking formula
both key off.

The work pack is explicit: "Seed them from the anomaly labels that actually appear in the
corpus — Smit's `eval/` script will enumerate them; do not hand-write the list from memory."
This script does that: it reads `eval/labels.json` (Smit's `Anomaly.*` label frequency count
over the corpus, `eval/score.py`'s output) when the file exists, and only falls back to a
pinned snapshot when it doesn't — which is the case on `main` today, since `eval/` lands on
Smit's branch. The snapshot below is that exact file's content as of 2026-09-09
(`git show origin/smit:eval/labels.json`), not a guess: 12 kept `Anomaly.*` labels with real
support counts (53 to 1,095 records) plus everything below the corpus's own ~30-record
cutoff folded into `other`. Re-run this script once `eval/labels.json` is on `main` and the
fallback stops being used — `seed()` logs which source it read.

Severity weights are the one number in this table that is a judgement call, not a fact
pulled from a source — the work pack says as much (§1.4: "a near-midair collision outweighs
an ATC staffing complaint"). The ordering below follows that logic: an airborne conflict or
a runway incursion carries immediate collision risk and sits highest; a procedural deviation
or an ATC staffing complaint is real but rarely imminent and sits lowest (above `other`,
which is `ranking.DEFAULT_SEVERITY` for a report with no hazard rows at all — unknown risk,
not zero risk). These are stored as data specifically so a later, better-justified weighting
is a dated row UPDATE, not a migration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.database import session_scope
from db.models import HazardCategory

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LABELS_JSON = _REPO_ROOT / "eval" / "labels.json"

#: Fallback snapshot of eval/labels.json (Smit's branch, captured 2026-09-09) — used only
#: while that file isn't yet on `main`. code -> (label, severity_weight).
_FALLBACK: dict[str, tuple[str, float]] = {
    "conflict": ("Conflict", 0.95),
    "ground_incursion": ("Ground Incursion", 0.90),
    "airspace_violation": ("Airspace Violation", 0.70),
    "flight_deck_cabin_aircraft_event": ("Flight Deck / Cabin / Aircraft Event", 0.65),
    "aircraft_equipment_problem": ("Aircraft Equipment Problem", 0.60),
    "ground_event_encounter": ("Ground Event / Encounter", 0.55),
    "deviation_altitude": ("Deviation - Altitude", 0.55),
    "deviation_track_heading": ("Deviation - Track / Heading", 0.50),
    "atc_issue": ("ATC Issue", 0.50),
    "deviation_speed": ("Deviation - Speed", 0.45),
    "deviation_discrepancy_procedural": ("Deviation / Discrepancy - Procedural", 0.40),
    "inflight_event_encounter": ("Inflight Event / Encounter", 0.40),
    # Below the corpus's ~30-record keep threshold (Ground Excursion: 27, No Specific
    # Anomaly Occurred: 20) and anything the classifier hasn't seen at all.
    "other": ("Other / Unclassified", 0.30),
}


def _slug(label: str) -> str:
    return (
        label.lower()
        .replace(" / ", "_")
        .replace("/", "_")
        .replace(" - ", "_")
        .replace("-", "_")
        .replace(" ", "_")
    )


def _load_labels() -> dict[str, tuple[str, float]]:
    if not _LABELS_JSON.exists():
        logger.info("eval/labels.json not found; using pinned fallback snapshot")
        return _FALLBACK

    data = json.loads(_LABELS_JSON.read_text())
    kept: list[str] = data["kept"]
    severity_by_label = {label: weight for _, (label, weight) in _severity_lookup(kept).items()}
    out: dict[str, tuple[str, float]] = {
        _slug(label): (label, severity_by_label[label]) for label in kept
    }
    out["other"] = _FALLBACK["other"]
    logger.info("loaded %d hazard labels from %s", len(out), _LABELS_JSON)
    return out


def _severity_lookup(kept_labels: list[str]) -> dict[str, tuple[str, float]]:
    """Map real corpus labels onto the judged severity ordering above, by label text — so a
    label surviving Smit's real `eval/labels.json` still gets a defensible weight even if the
    fallback's invented code slug doesn't match."""
    by_label = {label: (label, weight) for _, (label, weight) in _FALLBACK.items()}
    missing = [label for label in kept_labels if label not in by_label]
    if missing:
        raise ValueError(
            f"eval/labels.json has labels with no severity judgement yet: {missing}. "
            "Add them to _FALLBACK's severity ordering before seeding."
        )
    return {label: by_label[label] for label in kept_labels}


def seed(session: Session) -> int:
    """Insert any hazard_categories row that doesn't already exist by code. Idempotent —
    safe to run against a database that already has some or all of these rows."""
    labels = _load_labels()
    existing = set(session.execute(select(HazardCategory.code)).scalars())
    created = 0
    for code, (label, weight) in labels.items():
        if code in existing:
            continue
        session.add(HazardCategory(code=code, label=label, severity_weight=weight))
        created += 1
    return created


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with session_scope() as session:
        created = seed(session)
    logger.info("hazard_categories: %d row(s) created", created)


if __name__ == "__main__":
    main()
