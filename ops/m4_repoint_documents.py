"""M4: point document rows at the GCS bucket where their PDF was copied from MinIO.

Run inside the API container on the VM (reads DATABASE_URL from Secret Manager):
    gcloud compute ssh occurrence-desk-vm --zone us-central1-a \
      --command "sudo docker exec -i occdesk-m4-api-1 python -" < ops/m4_repoint_documents.py

Only rows whose object exists in the new bucket are changed; the rest are listed.
"""

from google.cloud import storage
from sqlalchemy import text

from db.database import get_engine

NEW, OLD = "occdesk-docs-occurrence-desk-2893", "occdesk-dev-docs"

bucket = storage.Client().bucket(NEW)
with get_engine().begin() as c:
    rows = c.execute(
        text("SELECT id, s3_key, status FROM documents WHERE s3_bucket = :b ORDER BY id"),
        {"b": OLD},
    ).all()
    moved = 0
    for doc_id, key, status in rows:
        if bucket.blob(key).exists():
            c.execute(
                text("UPDATE documents SET s3_bucket = :n WHERE id = :i"), {"n": NEW, "i": doc_id}
            )
            moved += 1
        else:
            print("no object for document", doc_id, "status", status, "key", key)
    print("repointed", moved, "of", len(rows))
    print(c.execute(text("SELECT s3_bucket, count(*) FROM documents GROUP BY 1 ORDER BY 1")).all())
