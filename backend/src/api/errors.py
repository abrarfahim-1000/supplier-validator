"""Structured error responses.

Every failure leaves the API in one shape, `{"error": {"code": ..., "message": ...}}`, with a
stable code the frontend can switch on and a message that is safe to show. Stack traces and
configuration values never reach the client.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Job and result lookups.
JOB_NOT_FOUND = "job_not_found"
RESULTS_NOT_READY = "results_not_ready"
JOB_FAILED = "job_failed"

# Admission control.
TOO_MANY_JOBS = "too_many_jobs"
RATE_LIMITED = "rate_limited"

# Uploads.
INVALID_REQUEST = "invalid_request"
INVALID_PURCHASE_REQUEST = "invalid_purchase_request"
NO_SUPPLIER_DOCUMENTS = "no_supplier_documents"
TOO_MANY_DOCUMENTS = "too_many_documents"
UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
INVALID_PDF = "invalid_pdf"
FILE_TOO_LARGE = "file_too_large"
EMPTY_FILE = "empty_file"
DUPLICATE_FILE = "duplicate_file"

# Everything else.
INTERNAL_ERROR = "internal_error"
CONFIGURATION_ERROR = "configuration_error"


class ApiError(Exception):
    """An expected failure that maps onto a status code and a stable code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(code, message))


def _handle_api_error(request: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, ApiError) else ApiError(500, INTERNAL_ERROR, "unexpected error")
    return _response(error.status_code, error.code, error.message)


def _field_name(location: tuple[int | str, ...]) -> str:
    parts = [str(part) for part in location if part != "body"]
    return ".".join(parts) or "request"


def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return _response(400, INVALID_REQUEST, "the request is invalid")
    errors = exc.errors()
    if not errors:
        return _response(400, INVALID_REQUEST, "the request is invalid")
    first = errors[0]
    return _response(
        400,
        INVALID_REQUEST,
        f"the request is invalid: {_field_name(first.get('loc', ()))} is missing or malformed",
    )


_HTTP_CODES = {
    404: "not_found",
    405: "method_not_allowed",
    415: UNSUPPORTED_FILE_TYPE,
}


def _handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return _response(500, INTERNAL_ERROR, "unexpected error")
    code = _HTTP_CODES.get(exc.status_code, "request_failed")
    detail = exc.detail if isinstance(exc.detail, str) else "the request could not be handled"
    return _response(exc.status_code, code, detail)


def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled API error on %s %s: %s",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return _response(500, INTERNAL_ERROR, "the server could not complete the request")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(Exception, _handle_unexpected)
