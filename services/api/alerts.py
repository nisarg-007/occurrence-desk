"""Critical-priority alerting.

Posts a Slack-compatible message (`{"text": "..."}`) to `settings.webhook_url` the moment a
report's score crosses into "needs attention" territory - the exact same `priority >= 70`
floor the worklist's "Needs attention" stat tile already uses
(`services/api/main.py::stats_fragment`, `web/templates/_stats.html`) and the "critical" band
in `presentation.BANDS`. No new threshold is invented here; `CRITICAL_THRESHOLD` is read off
that existing band.

**Where this fires from:** `services/worker/sql_store.py::save_reports`, right after
`db/priority.refresh_priorities` recomputes `reports.priority` for a newly-inserted report.
That is the one place a report transitions from "just parsed" to "scored" - the natural
trigger the worker lane already has, not a new call site invented for this feature.

**De-dup:** a report only ever gets inserted once (`reports.acn` is UNIQUE, enforced by the
database, and `save_reports` only calls this for report ids it just inserted for the first
time) - so the DB-level idempotency already covers "the same document parsed twice". The
extra in-process `_alerted` set below is a second, cheaper line of defence against the one
remaining case that isn't a database write: a worker process that alerts, then crashes and
gets restarted, re-processing the same already-inserted acn. `save_reports` never re-calls
this for that acn (the INSERT is a no-op the second time and it's skipped), so in practice a
migration-backed column would track nothing this in-process set doesn't already catch. A
missed or duplicated Slack ping is a bounded, non-destructive nuisance - not the kind of
silent data loss the README's idempotency story exists to prevent - so a real column adding
a migration and a write on every scoring pass was judged not worth it. If alerting needs to
survive a restart exactly-once later, this is the one function to change.
"""

from __future__ import annotations

import logging
import threading

import httpx

from services.api.presentation import BANDS
from services.common.settings import Settings

logger = logging.getLogger("api.alerts")

#: The "critical" band's floor - see module docstring. BANDS is ordered highest-first, so
#: index 0 is ("critical", ...).
CRITICAL_THRESHOLD = BANDS[0][0]

#: report_ids that have already fired an alert, this process's lifetime only. See module
#: docstring for why in-process state (not a migration) is the deliberate choice here.
_alerted: set[int] = set()


def reset_alerted() -> None:
    """Test-only: clear the in-process de-dup set between test cases."""
    _alerted.clear()


def maybe_alert(
    *,
    report_id: int,
    acn: str,
    priority: int,
    hazard_label: str | None,
    settings: Settings,
) -> None:
    """Fire a webhook alert if, and only if, this report just crossed the critical threshold
    and hasn't already alerted once. Safe to call on every scoring pass - below-threshold and
    already-alerted reports are both silent no-ops.
    """
    if priority < CRITICAL_THRESHOLD:
        return
    if not settings.webhook_url:
        return
    if report_id in _alerted:
        return
    _alerted.add(report_id)
    # Fire-and-forget, off the calling thread - the same pattern worker.py's own
    # VisibilityHeartbeat already uses to keep a slow network call off the parse path. A
    # webhook failure must never break report processing, so errors are logged, not raised.
    threading.Thread(
        target=_send,
        args=(settings.webhook_url, report_id, acn, priority, hazard_label),
        daemon=True,
    ).start()


def _send(
    webhook_url: str, report_id: int, acn: str, priority: int, hazard_label: str | None
) -> None:
    link = f"/console/reports/{report_id}"
    text = (
        f":rotating_light: *Critical-priority report* — ACN {acn} scored {priority}"
        f"{f' ({hazard_label})' if hazard_label else ''}\n"
        f"<{link}|Open in Occurrence Desk>"
    )
    try:
        httpx.post(webhook_url, json={"text": text}, timeout=5.0)
    except Exception:
        logger.exception("webhook POST failed for report_id=%s", report_id)
