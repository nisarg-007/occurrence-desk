"""Charts as inline SVG, rendered on the server.

No charting library. The console is server-rendered and has to work with the network off,
so a 40 kB JS dependency to draw four bars would be the wrong trade. These are pure
functions - data in, markup out - which also makes the geometry testable, and chart
geometry is exactly the kind of thing that goes quietly wrong.

Rules followed here, and why:

* **One axis.** Never two scales on one chart. Two measures of different size get two charts.
* **Colour never carries identity alone.** Every series is direct-labelled; the mark is
  `currentColor` so the caller sets it from a token and it follows the theme.
* **Rounded data-ends, thin marks, recessive axes.** The data should be the darkest thing.
* **Every chart is also text.** `role="img"` plus an `aria-label` that states the actual
  numbers, so the dashboard is not a wall of pictures to a screen reader, and a `<table>`
  fallback lives beside the ones that carry detail.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

BAR_RADIUS = 4
BAR_HEIGHT = 14
BAR_GAP = 10
LABEL_W = 168
VALUE_W = 44
#: Gap between a full-width bar's right edge and its value label. Has to exceed the
#: rendered width of the widest value we draw (up to 3 digits, tabular figures at
#: 11px) or the label sits on top of the bar when that row is the chart's max - found
#: by rendering the chart and looking at it, not by reasoning about the geometry.
VALUE_GAP = 20
#: Longer than this, a category name is truncated with an ellipsis rather than
#: overrunning into the bar next to it. The full name always survives in aria-label.
LABEL_MAX_CHARS = 20


@dataclass(frozen=True)
class Datum:
    label: str
    value: float
    #: CSS colour for the mark. Defaults to the element's currentColor.
    color: str | None = None
    #: Optional second line under the label (e.g. a share).
    note: str | None = None


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def _fmt(v: float) -> str:
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}"


def _truncate(label: str, max_chars: int = LABEL_MAX_CHARS) -> str:
    """The visual label only - the full name is always what aria-label states, so
    truncation here never removes information, it just stops one row's text from
    running into the next column."""
    return label if len(label) <= max_chars else label[: max_chars - 1].rstrip() + "…"


def bars(data: list[Datum], *, width: int = 520, unit: str = "", title: str = "") -> str:
    """Horizontal bars on a shared 0..max axis. The form for 'compare named magnitudes'."""
    if not data:
        return '<p class="muted" style="margin:0">No data yet.</p>'

    top = max((d.value for d in data), default=0) or 1
    plot_w = max(60, width - LABEL_W - VALUE_W - 16)
    height = len(data) * (BAR_HEIGHT + BAR_GAP)

    rows = []
    for i, d in enumerate(data):
        y = i * (BAR_HEIGHT + BAR_GAP)
        w = max(2, round(plot_w * (d.value / top)))
        # Every caller today only ever passes a hardcoded var(--sev-*) string, but this is an
        # attribute value built by string interpolation - escape it like every other piece of
        # text in this function rather than trusting that callers will always stay that way.
        fill = _esc(d.color) if d.color else "currentColor"
        # <title> gives a mouse-hover tooltip with the untruncated name, on top of the
        # full name already carried in the chart's own aria-label.
        rows.append(
            f'<text x="0" y="{y + 11}" class="c-label">'
            f"<title>{_esc(d.label)}</title>{_esc(_truncate(d.label))}</text>"
            f'<rect x="{LABEL_W}" y="{y}" width="{w}" height="{BAR_HEIGHT}" '
            f'rx="{BAR_RADIUS}" fill="{fill}"/>'
            f'<text x="{LABEL_W + plot_w + VALUE_GAP}" y="{y + 11}" class="c-value" '
            f'text-anchor="end">{_fmt(d.value)}</text>'
        )

    summary = ", ".join(f"{d.label} {_fmt(d.value)}{unit}" for d in data)
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="{_esc(title + ": " if title else "")}{_esc(summary)}">'
        f"{''.join(rows)}</svg>"
    )


def columns(
    labels: list[str],
    values: list[float],
    *,
    width: int = 520,
    height: int = 140,
    title: str = "",
    every: int = 1,
) -> str:
    """Vertical columns for a value over ordered periods. Discrete periods, so columns -
    a line would imply we measured something between the months."""
    if not values:
        return '<p class="muted" style="margin:0">No data yet.</p>'

    top = max(values) or 1
    plot_h = height - 22
    slot = width / len(values)
    bar_w = max(3, min(26, slot * 0.62))

    marks, ticks = [], []
    for i, (lab, v) in enumerate(zip(labels, values, strict=True)):
        h = max(2, round(plot_h * (v / top)))
        x = i * slot + (slot - bar_w) / 2
        marks.append(
            f'<rect x="{x:.1f}" y="{plot_h - h}" width="{bar_w:.1f}" height="{h}" '
            f'rx="{BAR_RADIUS}" fill="currentColor"/>'
        )
        if i % every == 0 or i == len(values) - 1:
            ticks.append(
                f'<text x="{i * slot + slot / 2:.1f}" y="{height - 4}" class="c-tick" '
                f'text-anchor="middle">{_esc(lab)}</text>'
            )

    summary = ", ".join(f"{lab} {_fmt(v)}" for lab, v in zip(labels, values, strict=True))
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="{_esc(title + ": " if title else "")}{_esc(summary)}">'
        f'<line x1="0" y1="{plot_h}" x2="{width}" y2="{plot_h}" class="c-axis"/>'
        f"{''.join(marks)}{''.join(ticks)}</svg>"
    )


def sparkline(
    values: list[float],
    *,
    width: int = 520,
    height: int = 64,
    title: str = "",
    threshold: float | None = None,
    threshold_label: str = "",
) -> str:
    """A single measure over time, with an optional target line.

    The target line is the point of this chart: 'the latency stayed under the line' is the
    claim, so the line has to be *on* the chart rather than in the caption.
    """
    if len(values) < 2:
        return (
            '<p class="muted" style="margin:0">Collecting — the line appears once there '
            "are a few samples.</p>"
        )

    top = max(max(values), threshold or 0) * 1.15 or 1
    plot_h = height - 14
    step = width / (len(values) - 1)
    pts = [(i * step, plot_h - (v / top) * plot_h) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,{plot_h} {line} {width},{plot_h}"

    rule = ""
    if threshold is not None:
        ty = plot_h - (threshold / top) * plot_h
        rule = (
            f'<line x1="0" y1="{ty:.1f}" x2="{width}" y2="{ty:.1f}" class="c-threshold"/>'
            f'<text x="{width}" y="{ty - 5:.1f}" class="c-tick" text-anchor="end">'
            f"{_esc(threshold_label)}</text>"
        )

    last_x, last_y = pts[-1]
    summary = (
        f"{title}: latest {_fmt(values[-1])}, "
        f"min {_fmt(min(values))}, max {_fmt(max(values))} over {len(values)} samples"
    )
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="{_esc(summary)}">'
        f'<polygon points="{area}" class="c-area"/>'
        f'<polyline points="{line}" class="c-line"/>'
        f"{rule}"
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4" class="c-point"/>'
        f"</svg>"
    )
