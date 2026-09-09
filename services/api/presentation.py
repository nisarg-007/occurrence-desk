"""Turning numbers into things a person can read at a glance.

The one rule here: **never encode meaning in colour alone.** A priority of 84 and a
priority of 31 must be distinguishable to someone who cannot tell red from green, in a
printout, and to a screen reader. So every score carries a band name as text, and the
console draws a four-step meter beside it. Colour is the third encoding, not the first.
"""

from __future__ import annotations

#: Bands are inclusive lower bounds, highest first. The cuts are deliberate, not
#: quartiles: 70 is "a severe hazard, or a linked and recent one", 40 is "worth reading
#: today", below 15 is "nothing on this report suggests urgency".
BANDS: tuple[tuple[int, str, str], ...] = (
    (70, "critical", "Critical"),
    (40, "high", "High"),
    (15, "moderate", "Moderate"),
    (0, "low", "Low"),
)


def level(priority: int) -> tuple[str, str]:
    """(machine level, human label) for a 0-100 priority."""
    for floor, key, label in BANDS:
        if priority >= floor:
            return key, label
    return "low", "Low"
