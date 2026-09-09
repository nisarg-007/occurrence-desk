"""The chart functions are pure - data in, markup out - so geometry and escaping are
testable without a browser. This is what catches a chart going quietly wrong."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from services.api import charts

# The markup has no xmlns declaration (it's inlined straight into an HTML5 page, where the
# parser assigns the SVG namespace implicitly) - parsed standalone here, elements come back
# unqualified, so tag lookups use plain names rather than a namespaced prefix.
SVG_NS = ""


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def test_bars_empty_data_is_not_a_zero_height_svg():
    assert "<svg" not in charts.bars([])


def test_bars_widths_are_proportional_to_value():
    data = [charts.Datum("A", 100), charts.Datum("B", 50)]
    root = _parse(charts.bars(data, width=520))
    rects = root.findall(f"{SVG_NS}rect")
    assert len(rects) == 2
    w_a, w_b = float(rects[0].get("width")), float(rects[1].get("width"))
    assert w_a == 2 * w_b


def test_bars_zero_value_still_gets_a_visible_sliver():
    """A zero-count band must still be findable on screen, not an invisible 0px rect -
    disappearing entirely reads as 'this band doesn't exist' rather than 'it's empty'."""
    data = [charts.Datum("Empty", 0), charts.Datum("Full", 10)]
    root = _parse(charts.bars(data))
    widths = [float(r.get("width")) for r in root.findall(f"{SVG_NS}rect")]
    assert min(widths) >= 2


def test_bars_role_and_label_state_the_real_numbers():
    data = [charts.Datum("Bird strike", 12), charts.Datum("Runway incursion", 4)]
    svg = charts.bars(data, title="Reports by hazard category")
    root = _parse(svg)
    assert root.get("role") == "img"
    label = root.get("aria-label")
    assert "Reports by hazard category" in label
    assert "Bird strike 12" in label
    assert "Runway incursion 4" in label


def test_bars_escapes_label_text():
    svg = charts.bars([charts.Datum("<script>alert(1)</script>", 1)])
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_bars_per_datum_colour_overrides_current_colour():
    svg = charts.bars([charts.Datum("A", 1, color="var(--sev-critical)")])
    assert 'fill="var(--sev-critical)"' in svg


def test_columns_one_bar_per_value_with_matching_ticks():
    months = ["Jan", "Feb", "Mar"]
    counts = [3, 7, 1]
    root = _parse(charts.columns(months, counts, every=1))
    assert len(root.findall(f"{SVG_NS}rect")) == 3
    ticks = [t.text for t in root.findall(f"{SVG_NS}text")]
    assert ticks == months


def test_columns_every_thins_the_ticks_but_keeps_all_bars():
    months = [f"M{i}" for i in range(12)]
    counts = [1] * 12
    root = _parse(charts.columns(months, counts, every=3))
    assert len(root.findall(f"{SVG_NS}rect")) == 12
    # every=3 keeps indices 0,3,6,9, plus the last (11) so the axis never dead-ends early
    assert len(root.findall(f"{SVG_NS}text")) == 5


def test_columns_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        charts.columns(["Jan", "Feb"], [1])


def test_sparkline_needs_at_least_two_points():
    assert "<svg" not in charts.sparkline([])
    assert "<svg" not in charts.sparkline([42])


def test_sparkline_draws_a_point_per_sample():
    root = _parse(charts.sparkline([10, 20, 15, 30]))
    line = root.find(f"{SVG_NS}polyline")
    assert len(line.get("points").split()) == 4


def test_sparkline_threshold_line_is_drawn_and_labelled():
    svg = charts.sparkline([10, 20], threshold=15, threshold_label="200 ms target")
    root = _parse(svg)
    assert root.find(f"{SVG_NS}line") is not None
    assert "200 ms target" in svg


def test_sparkline_last_point_is_marked():
    root = _parse(charts.sparkline([1, 2, 3]))
    assert root.find(f"{SVG_NS}circle") is not None
