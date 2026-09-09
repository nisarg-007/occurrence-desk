"""Measure how long it takes to parse one document (one uploaded PDF, ~50
ASRS records) end to end - this is the number Sowmya's visibility timeout
and autoscaling target both derive from directly (work-pack, sections 5.3
and 5.4): visibility_timeout should sit comfortably above our measured p99,
and the autoscaling target is acceptable_latency / mean_parse_time.

Measures parse_pdf() only - not the S3 download, not the database write.
Those add real but separate latency once the full stack exists; this is the
CPU-bound part that is ours to own and that will not change when the queue
or the database do.

    python tests/bench/bench_parse.py
"""

from __future__ import annotations

import glob
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.worker.parser import parse_pdf  # noqa: E402


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[idx]


def main() -> int:
    pdf_paths = sorted(glob.glob("services/worker/sample_pdfs/*.pdf"))
    if not pdf_paths:
        print("No sample PDFs found locally - download the 30 report sets first (see the README).")
        return 1

    # warm up the disk cache / import machinery on one file before timing
    parse_pdf(pdf_paths[0], document_id=1)

    samples_ms: list[float] = []
    for path in pdf_paths:
        started = time.perf_counter()
        records = parse_pdf(path, document_id=1)
        elapsed_ms = (time.perf_counter() - started) * 1000
        samples_ms.append(elapsed_ms)
        assert len(records) == 50, f"{path}: expected 50 records, got {len(records)}"

    print(f"n={len(samples_ms)} documents (one full report-set PDF each, ~50 records)")
    print(f"  mean {statistics.fmean(samples_ms):7.1f} ms")
    print(f"  p50  {percentile(samples_ms, 50):7.1f} ms")
    print(f"  p95  {percentile(samples_ms, 95):7.1f} ms")
    print(f"  p99  {percentile(samples_ms, 99):7.1f} ms")
    print(f"  max  {max(samples_ms):7.1f} ms")
    print(f"  per-record mean: {statistics.fmean(samples_ms) / 50:.2f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
