"""Pydantic v2 models. These mirror contracts/openapi.yaml - if they drift, the contract wins."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

Role = Literal["analyst", "manager", "admin"]
DocumentStatus = Literal["received", "queued", "parsing", "parsed", "failed"]
DispositionState = Literal["new", "triaged", "escalated", "closed"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    role: Role


class UploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class UploadUrlResponse(BaseModel):
    document_id: int
    url: str
    fields: dict[str, str]
    expires_in: int
    duplicate: bool


class AcceptedResponse(BaseModel):
    document_id: int
    status: DocumentStatus
    enqueued: bool
    trace_id: str


class Hazard(BaseModel):
    code: str
    label: str
    confidence: float
    source: Literal["nasa", "model"]


class FlightLink(BaseModel):
    flight_id: int
    confidence: float
    method: str
    flight_date: dt.date | None = None
    carrier: str | None = None
    origin: str | None = None
    dest: str | None = None


class ReportSummary(BaseModel):
    id: int
    acn: str
    report_date: dt.date | None = None
    synopsis: str | None = None
    priority: int
    state: DispositionState
    assigned_to: int | None = None
    hazards: list[Hazard] = []


class ReportDetail(ReportSummary):
    document_id: int
    narrative: str
    coded: dict[str, Any] = {}
    linked_flight: FlightLink | None = None


class ReportPage(BaseModel):
    items: list[ReportSummary]
    next_cursor: str | None
    page_size: int


class Document(BaseModel):
    id: int
    sha256: str
    original_filename: str | None = None
    byte_size: int | None = None
    page_count: int | None = None
    status: DocumentStatus
    attempts: int
    error_text: str | None = None
    uploaded_at: dt.datetime
    reports: list[ReportSummary] = []


class DispositionRequest(BaseModel):
    state: DispositionState
    priority: int | None = Field(default=None, ge=0, le=100)
    note: str | None = Field(default=None, max_length=4000)


class Disposition(BaseModel):
    id: int
    report_id: int
    analyst_id: int
    state: DispositionState
    priority: int | None = None
    note: str | None = None
    created_at: dt.datetime


class AssignRequest(BaseModel):
    analyst_id: int
    manager_flagged: bool = False


class PriorityTerm(BaseModel):
    name: str
    weight: float
    value: float
    product: float
    explanation: str


class PriorityExplanation(BaseModel):
    report_id: int
    priority: int
    formula: str
    terms: list[PriorityTerm]


class QueueStats(BaseModel):
    visible: int
    in_flight: int
    oldest_message_age_seconds: int | None = None
    dlq_depth: int = 0
    workers: int
    throughput_per_min: float
    drain_eta_seconds: int | None = None
    estimating: bool
    cached_for_seconds: int


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class Readiness(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]
