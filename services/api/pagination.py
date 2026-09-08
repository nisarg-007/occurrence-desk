"""Keyset pagination over (priority DESC, report_date DESC, id DESC).

Not OFFSET. `OFFSET 50000` reads fifty thousand rows and throws them away; under the replay
that is exactly when the console goes dark. The cursor is an opaque base64 of the sort tuple,
so clients cannot hand-craft one and we can change the tuple without changing the API shape.

The composite index this needs is Parva's to create (that is a conversation, not a unilateral
migration):

    CREATE INDEX ON reports (priority DESC, report_date DESC, id DESC);
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from dataclasses import dataclass


class InvalidCursor(ValueError):
    pass


@dataclass(frozen=True)
class Cursor:
    priority: int
    report_date: dt.date | None
    report_id: int

    def encode(self) -> str:
        raw = json.dumps(
            {
                "p": self.priority,
                "d": self.report_date.isoformat() if self.report_date else None,
                "i": self.report_id,
            },
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> Cursor:
        try:
            padded = token + "=" * (-len(token) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded))
            return cls(
                priority=int(data["p"]),
                report_date=dt.date.fromisoformat(data["d"]) if data["d"] else None,
                report_id=int(data["i"]),
            )
        except Exception as exc:  # noqa: BLE001 - any malformed cursor is one error to the client
            raise InvalidCursor(f"malformed cursor: {token!r}") from exc


#: Sorts DESC on (priority, report_date, id). A null report_date sorts last, which matches
#: `ORDER BY priority DESC, report_date DESC NULLS LAST, id DESC` in Postgres.
def sort_key(priority: int, report_date: dt.date | None, report_id: int) -> tuple:
    return (
        -priority,
        0 if report_date else 1,
        -report_date.toordinal() if report_date else 0,
        -report_id,
    )


def after(cursor: Cursor) -> tuple:
    """The sort position to page strictly after."""
    return sort_key(cursor.priority, cursor.report_date, cursor.report_id)
