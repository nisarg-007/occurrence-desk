"""
Capture the README's screenshots from the running local stack.

Not a test and not part of the app - a documentation tool. Run it against a
stack that already has documents parsed, so the worklist is not empty:

    make up
    python docs/capture_screenshots.py

Writes PNGs into docs/images/. Re-run after a UI change rather than editing
the README by hand.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path("docs/images")
VIEWPORT = {"width": 1440, "height": 900}

# (filename, path, wait_for_selector_or_None, full_page)
#
# full_page is used sparingly: a report's narrative runs thousands of pixels,
# and a full-page capture of it renders as an unreadable sliver in the README
# (and weighs megabytes). Viewport shots of the part that matters beat a
# complete shot of something nobody can read.
SHOTS = [
    ("console-worklist.png", "/console", None, False),
    ("console-dashboard.png", "/console/dashboard", None, True),
    ("console-upload.png", "/console/upload", None, False),
]


def first_report_id(page) -> str | None:
    """Grab a real report id from the worklist so the detail shot isn't a 404."""
    page.goto(f"{BASE}/console", wait_until="networkidle")
    link = page.locator('a[href^="/console/reports/"]').first
    if link.count() == 0:
        return None
    href = link.get_attribute("href") or ""
    return href.rsplit("/", 1)[-1] or None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

        # APP_ENV=local auto-signs in; hit it once so the session cookie exists.
        page.goto(f"{BASE}/console/dev-session", wait_until="networkidle")

        for name, path, selector, full in SHOTS:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            if selector:
                page.wait_for_selector(selector, timeout=10_000)
            page.wait_for_timeout(1200)  # let chart entrance animations settle
            page.screenshot(path=str(OUT / name), full_page=full)
            print(f"captured {name}")

        report_id = first_report_id(page)
        if report_id:
            page.goto(f"{BASE}/console/reports/{report_id}", wait_until="networkidle")
            page.wait_for_timeout(800)
            # viewport only: the score breakdown and hazard cards are the point,
            # and they sit above the fold. The narrative below runs for pages.
            page.screenshot(path=str(OUT / "console-report-detail.png"), full_page=False)
            print(f"captured console-report-detail.png (report {report_id})")
        else:
            print("no reports in the worklist - skipped the detail shot", file=sys.stderr)

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
