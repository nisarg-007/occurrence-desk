"""
Stage 5: run the parser on the whole PDF and save the result in the exact
shape the team agreed on - contracts/extraction-record.schema.json.

Every record is validated against that schema before being saved, so if our
output doesn't match what Parva/Nisarg are expecting, we find out right here
- not when someone else's code tries to read it.

Run from the repo root:
    python services/worker/extract_records.py
"""

import json

from jsonschema import Draft202012Validator

from parser import parse_pdf

PDF_PATH = "services/worker/sample_pdfs/nmac.pdf"
SCHEMA_PATH = "contracts/extraction-record.schema.json"
OUTPUT_PATH = "services/worker/output/nmac_extracted.json"

with open(SCHEMA_PATH) as f:
    schema = json.load(f)
validator = Draft202012Validator(schema)

records = parse_pdf(PDF_PATH, document_id=1)
print(f"Parsed {len(records)} records (expected 50)")

errors_found = 0
for record in records:
    errors = sorted(validator.iter_errors(record), key=str)
    if errors:
        errors_found += 1
        print(f"\nACN {record['acn']} FAILED schema validation:")
        for e in errors:
            print(f"  - {'.'.join(str(p) for p in e.path)}: {e.message}")

if errors_found:
    print(f"\n{errors_found} of {len(records)} records failed validation.")
else:
    print("All 50 records match contracts/extraction-record.schema.json.")

import os

os.makedirs("services/worker/output", exist_ok=True)
with open(OUTPUT_PATH, "w") as f:
    json.dump(records, f, indent=2)
print(f"\nSaved to {OUTPUT_PATH}")

# print one full record so it's easy to eyeball against the original PDF
sample = records[0]
print(f"\n--- Full example: ACN {sample['acn']} (pages {sample['page_from']}-{sample['page_to']}) ---")
print(json.dumps(sample, indent=2)[:3000])
print("... (truncated)")
