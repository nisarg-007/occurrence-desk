# Worker lane — extraction, classification, reproducing the numbers

Owner: Smit. Everything between "a PDF exists in S3" and "structured rows exist
in Postgres".

## The two artefacts that are NOT in git, and why

| Artefact | Why it's gitignored | How to regenerate |
|---|---|---|
| `sample_pdfs/*.pdf` (30 files, ~19 MB) | `.gitignore` excludes `*.pdf`; it's public federal data, downloadable on demand | `python services/worker/fetch_report_sets.py` |
| `model/hazard_model.joblib` (~20 MB) | `.gitignore` excludes `services/worker/model/`; a derived binary, not source | `python services/worker/classifier.py` |

**This matters more than it looks.** `hazards.py` deliberately does *not* raise
when the model file is missing — it returns an empty list, so a document still
gets its `source='nasa'` hazards and its narrative. That's the right behaviour
for a missing optional artefact, but it means a fresh clone silently produces
**no `source='model'` predictions at all** and nothing looks broken. If the
worklist shows only `nasa` hazards and never `model` ones, this is why.

Same story for the PDFs: the parser itself never touches `sample_pdfs/` (it
parses whatever was uploaded to S3), but `classifier.py` and `eval/score.py`
both do, and the PDF-dependent tests `skip` rather than fail without them.

## Reproducing the lane's numbers from a fresh clone

```bash
python services/worker/fetch_report_sets.py   # 30 NASA report sets, ~19 MB, idempotent
python services/worker/classifier.py          # trains + writes model/, eval/labels.json, eval/report.md
python eval/score.py                          # extraction P/R/F1 vs the hand-verified gold records
python -m pytest tests/unit/test_parser.py tests/unit/test_worker.py -q
```

Do the first two **before** `make up` if you want `source='model'` hazards in
the container: `infra/docker/worker.Dockerfile` copies the build context, so the
model is baked into the image at build time, not fetched at runtime.

Current measured values, with the commands that produced them, live in
`docs/measurements.md` — not here, so there is one place to look and one place
to keep honest.

## Parser behaviours worth knowing

- **`Callback: N` blocks fold into `narrative`.** ASRS sometimes appends an
  analyst's follow-up note to a report. The extraction contract has no
  `callback` field, so that prose lands in `narrative` alongside the
  reporter's own. Deliberate, not an oversight — but it means narrative text
  is occasionally reporter + analyst, which matters if you are training on it.
- **`report_date` is always null.** NASA's `Date` is `YYYYMM` — month
  precision, no day. Rather than invent a day to satisfy a `date` type, the
  raw value stays verbatim in `coded` / `fields` and the typed column stays
  empty.
- **Hazards are deduplicated per axis.** `Anomaly.Conflict : NMAC` and a
  second `Anomaly.Conflict` value on the same record produce one `nasa`
  hazard row, because `report_hazards` is keyed
  `(report_id, category_id, source)`. The sub-values survive in `fields`.

## Layout

| File | What it does |
|---|---|
| `parser.py` | PDF → structured records. Owns the `hazards` rows with `source='nasa'`. |
| `worker.py` | SQS consume → claim → download → parse → save → delete. Retries and DLQ behaviour. |
| `store.py` | Backend seam: `sql_store.py` (Postgres) or `json_store.py` (offline tests). |
| `classifier.py` | Trains TF-IDF + LinearSVC on narratives; writes the model and the eval report. |
| `hazards.py` | Loads the trained model, adds `source='model'` rows. Degrades to `[]` if absent. |
| `fetch_report_sets.py` | Downloads the 30 NASA report-set PDFs. |
| `extract_records.py`, `find_records.py`, `inspect_pdf.py` | Development scripts used while building the parser. |
| `local_stack_test.py` | End-to-end exercise against a local S3 + SQS, including the poison-PDF path. |
