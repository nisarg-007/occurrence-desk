"""RFC 7807 problem+json. One error shape for the whole API."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from services.common.logging import request_id_var

BASE = "https://occdesk/errors/"


class ApiProblem(Exception):
    def __init__(self, status: int, title: str, detail: str = "", type_: str | None = None):
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_ or BASE + title.lower().replace(" ", "-")
        super().__init__(f"{status} {title}: {detail}")


def problem_response(request: Request, exc: ApiProblem) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        media_type="application/problem+json",
        content={
            "type": exc.type,
            "title": exc.title,
            "status": exc.status,
            "detail": exc.detail,
            "instance": str(request.url.path),
            "request_id": request_id_var.get(),
        },
    )


def unauthorized(detail: str = "missing or invalid token") -> ApiProblem:
    return ApiProblem(401, "Unauthorized", detail)


def forbidden(detail: str) -> ApiProblem:
    return ApiProblem(403, "Forbidden", detail)


def not_found(what: str) -> ApiProblem:
    return ApiProblem(404, "Not Found", f"no such {what}")


def too_large(detail: str) -> ApiProblem:
    return ApiProblem(413, "Payload Too Large", detail)


def conflict(detail: str) -> ApiProblem:
    return ApiProblem(409, "Conflict", detail)
