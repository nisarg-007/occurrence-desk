"""The two-step upload, and the 202 that defines the project.

`POST /documents/{id}/complete` writes a row, sends one SQS message, and returns. It does not
open a PDF. If parsing ever creeps onto this path, the project has lost its thesis.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from fastapi import APIRouter, Depends, Response, status

from services.api import problems
from services.api.deps import analyst, get_repo, settings
from services.api.repo import Repository
from services.api.schemas import (
    AcceptedResponse,
    Document,
    Hazard,
    ReportSummary,
    UploadUrlRequest,
    UploadUrlResponse,
)
from services.api.security import Principal
from services.common import aws
from services.common.logging import trace_id_var
from services.common.settings import Settings

router = APIRouter(prefix="/documents", tags=["documents"])


def object_key(sha256: str, when: dt.date | None = None) -> str:
    """Content-addressed: the same PDF always lands on the same key, so a duplicate upload
    overwrites itself into an identical object and the sha256 unique constraint does the rest."""
    when = when or dt.datetime.now(dt.UTC).date()
    return f"raw/{when:%Y/%m/%d}/{sha256}.pdf"


@router.post("/upload-url", response_model=UploadUrlResponse)
def upload_url(
    body: UploadUrlRequest,
    p: Principal = Depends(analyst),
    repo: Repository = Depends(get_repo),
    s: Settings = Depends(settings),
) -> UploadUrlResponse:
    if body.byte_size > s.max_upload_bytes:
        raise problems.too_large(
            f"byte_size {body.byte_size} exceeds MAX_UPLOAD_BYTES {s.max_upload_bytes}"
        )

    existing = repo.document_by_sha(body.sha256)
    key = existing.s3_key if existing else object_key(body.sha256)
    doc = existing or repo.create_document(
        sha256=body.sha256,
        s3_bucket=s.s3_bucket,
        s3_key=key,
        original_filename=body.filename,
        byte_size=body.byte_size,
        uploaded_by=p.user_id,
    )

    # Presigned POST, not PUT: only POST can enforce a size range and content type in the
    # policy, so an oversized file is rejected by S3 itself and never costs us a request,
    # a worker, or a byte of RDS.
    presigned = aws.s3().generate_presigned_post(
        Bucket=s.s3_bucket,
        Key=key,
        Fields={"Content-Type": "application/pdf"},
        Conditions=[
            {"Content-Type": "application/pdf"},
            ["content-length-range", 1, s.max_upload_bytes],
        ],
        ExpiresIn=s.presign_expires_seconds,
    )
    return UploadUrlResponse(
        document_id=doc.id,
        url=presigned["url"],
        fields=presigned["fields"],
        expires_in=s.presign_expires_seconds,
        duplicate=existing is not None,
    )


@router.post(
    "/{document_id}/complete",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def complete(
    document_id: int,
    response: Response,
    p: Principal = Depends(analyst),
    repo: Repository = Depends(get_repo),
    s: Settings = Depends(settings),
) -> AcceptedResponse:
    doc = repo.document(document_id)
    if doc is None:
        raise problems.not_found("document")

    trace_id = trace_id_var.get()
    enqueued = repo.mark_queued(document_id)

    if enqueued:
        message = {
            "schema_version": 1,
            "kind": "document.parse",
            "document_id": doc.id,
            "s3_bucket": doc.s3_bucket,
            "s3_key": doc.s3_key,
            "sha256": doc.sha256,
            "submitted_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            "trace_id": trace_id,
        }
        if s.sqs_queue_url:
            try:
                aws.sqs().send_message(
                    QueueUrl=s.sqs_queue_url,
                    MessageBody=json.dumps(message, separators=(",", ":")),
                )
            except Exception as exc:
                # The row already says 'queued'. If the send failed, that row is a lie: a
                # document waiting on a message that does not exist. Roll it back so the next
                # submit can enqueue it, and tell the caller the truth with a 503 rather than
                # a bare 500 - a stuck document is the silent loss our criteria forbid.
                repo.unmark_queued(doc.id)
                logging.getLogger("api.documents").error(
                    "enqueue failed",
                    extra={"document_id": doc.id, "error": str(exc)},
                )
                raise problems.ApiProblem(
                    503,
                    "Queue Unavailable",
                    "the document was accepted but could not be queued; retry shortly",
                ) from exc

    # Duplicate submission is normal, not exceptional: still 202, just enqueued=false.
    response.status_code = status.HTTP_202_ACCEPTED
    return AcceptedResponse(
        document_id=doc.id,
        status=doc.status,  # type: ignore[arg-type]
        enqueued=enqueued,
        trace_id=trace_id,
    )


def _summary(repo: Repository, r) -> ReportSummary:
    return ReportSummary(
        id=r.id,
        acn=r.acn,
        report_date=r.report_date,
        synopsis=r.synopsis,
        priority=repo.priority(r) if hasattr(repo, "priority") else 0,
        state=r.state,
        assigned_to=r.assigned_to,
        hazards=[Hazard(**h) for h in r.hazards],
    )


@router.get("/{document_id}", response_model=Document)
def get_document(
    document_id: int,
    p: Principal = Depends(analyst),
    repo: Repository = Depends(get_repo),
) -> Document:
    doc = repo.document(document_id)
    if doc is None:
        raise problems.not_found("document")
    return Document(
        id=doc.id,
        sha256=doc.sha256,
        original_filename=doc.original_filename,
        byte_size=doc.byte_size,
        page_count=doc.page_count,
        status=doc.status,  # type: ignore[arg-type]
        attempts=doc.attempts,
        error_text=doc.error_text,
        uploaded_at=doc.uploaded_at,
        reports=[_summary(repo, r) for r in repo.reports_for_document(document_id)],
    )
