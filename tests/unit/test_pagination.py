from __future__ import annotations

import datetime as dt

import pytest

from services.api.pagination import Cursor, InvalidCursor, sort_key


def test_cursor_round_trips():
    c = Cursor(87, dt.date(2026, 3, 1), 4412)
    assert Cursor.decode(c.encode()) == c


def test_cursor_round_trips_with_null_date():
    c = Cursor(12, None, 9)
    assert Cursor.decode(c.encode()) == c


def test_cursor_is_opaque_not_guessable_json():
    assert "4412" not in Cursor(87, dt.date(2026, 3, 1), 4412).encode()


def test_malformed_cursor_is_one_clean_error():
    with pytest.raises(InvalidCursor):
        Cursor.decode("not-a-cursor")


def test_sort_is_priority_then_date_then_id_all_descending():
    rows = [
        (50, dt.date(2026, 1, 1), 1),
        (90, dt.date(2020, 1, 1), 2),
        (90, dt.date(2026, 1, 1), 3),
        (90, dt.date(2026, 1, 1), 9),
    ]
    ordered = sorted(rows, key=lambda r: sort_key(*r))
    assert [r[2] for r in ordered] == [9, 3, 2, 1]


def test_null_dates_sort_last_within_a_priority():
    rows = [(50, None, 1), (50, dt.date(2026, 1, 1), 2)]
    ordered = sorted(rows, key=lambda r: sort_key(*r))
    assert [r[2] for r in ordered] == [2, 1]
