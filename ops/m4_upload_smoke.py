"""M4 upload smoke test: real API -> signed GCS POST -> queue -> worker.

Run inside the API container on the VM:
    gcloud compute ssh occurrence-desk-vm --zone us-central1-a \
      --command "sudo docker exec -i occdesk-m4-api-1 python -" < ops/m4_upload_smoke.py
"""

import datetime as dt
import hashlib
import time

import httpx

from services.api.main import API_PREFIX
from services.api.security import issue_token

BASE = "http://localhost:8000" + API_PREFIX
stamp = dt.datetime.now(dt.UTC).isoformat()
body = f"M4 upload test {stamp}"
pdf = (
    "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R>>endobj\n"
    f"4 0 obj<</Length {len(body) + 30}>>stream\n"
    f"BT /F1 12 Tf 10 50 Td ({body}) Tj ET\nendstream endobj\n"
    "trailer<</Root 1 0 R>>\n%%EOF\n"
).encode()
sha = hashlib.sha256(pdf).hexdigest()
headers = {"Authorization": "Bearer " + issue_token(1, "m4-smoke@occdesk.example", "analyst")}

r = httpx.post(
    f"{BASE}/documents/upload-url",
    headers=headers,
    json={"filename": "m4-upload-test.pdf", "byte_size": len(pdf), "sha256": sha},
)
print("upload-url:", r.status_code)
r.raise_for_status()
up = r.json()
print("signed POST target:", up["url"], "| fields:", sorted(up["fields"]))
print("signed as:", up["fields"].get("x-goog-credential", "").split("/")[0])

r = httpx.post(up["url"], data=up["fields"], files={"file": ("m4.pdf", pdf, "application/pdf")})
print("bucket POST:", r.status_code)
r.raise_for_status()

r = httpx.post(f"{BASE}/documents/{up['document_id']}/complete", headers=headers)
print("complete:", r.status_code, r.json())

for _ in range(30):
    doc = httpx.get(f"{BASE}/documents/{up['document_id']}", headers=headers).json()
    if doc.get("status") not in ("uploaded", "queued", "parsing"):
        break
    time.sleep(2)
print(
    "document",
    up["document_id"],
    "final status:",
    doc.get("status"),
    "|",
    doc.get("error_text") or "",
)
print("object key:", doc.get("s3_key"), "sha256:", sha)
