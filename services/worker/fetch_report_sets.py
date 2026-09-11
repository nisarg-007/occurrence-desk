"""
Download all 30 NASA ASRS report-set PDFs into services/worker/sample_pdfs/.

Without this, the corpus only ever existed on one machine (mine) - nobody
else could reproduce the extraction accuracy score, retrain the classifier,
or regenerate the model file. Idempotent: skips any PDF already present, so
it's safe to run anytime, including in CI.

Source: https://asrs.arc.nasa.gov/search/reportsets.html - free, public,
no registration, per the work-pack's own ground-truth section.

Run from the repo root:
    python services/worker/fetch_report_sets.py
"""

import urllib.request
from pathlib import Path

BASE_URL = "https://asrs.arc.nasa.gov/docs/rpsts/"
OUT_DIR = Path("services/worker/sample_pdfs")

REPORT_SETS = [
    "acr_fatg", "altdev", "animal", "cabin_fumes", "cftt", "chklist",
    "com_fatigue", "crm", "ctlr", "ems", "flt_attendant", "fuel", "ga_train",
    "gps", "helo", "icing", "mechanic", "nmac", "non_twr", "parachute",
    "pax", "ped", "penetrat", "plt_ctlr", "rnav_arrival", "rwy_incur",
    "uas", "upsets", "waketurb", "wx",
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetched, skipped = 0, 0
    for name in REPORT_SETS:
        dest = OUT_DIR / f"{name}.pdf"
        if dest.exists():
            skipped += 1
            continue
        url = f"{BASE_URL}{name}.pdf"
        print(f"Fetching {url} ...")
        with urllib.request.urlopen(url, timeout=30) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        fetched += 1

    print(f"\nDone: {fetched} downloaded, {skipped} already present, {len(REPORT_SETS)} total.")


if __name__ == "__main__":
    main()
