"""Response models for the API.

These are the contract: `contracts/openapi.json` is exported from them and the frontend
generates its TypeScript types from that file. Change a model here before either side is
implemented, never the other way round.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from checker.schemas import DocumentResult


class ProgressState(StrEnum):
    """Status of one document or one UI stage. The same four values everywhere."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobState(StrEnum):
    """Overall job state, polled by the frontend until it is terminal."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class StageStatusPayload(BaseModel):
    name: str = Field(description="Stage label, in the order the frontend shows it")
    status: ProgressState


class DocumentStatusPayload(BaseModel):
    id: str = Field(description="Server-generated document id, stable within the job")
    filename: str = Field(description="Original upload filename, for display only")
    state: ProgressState
    stages: list[StageStatusPayload]


class JobErrorPayload(BaseModel):
    code: str
    message: str


class JobCreatedResponse(BaseModel):
    id: str
    state: JobState
    documents_total: int
    created_at: str = Field(description="ISO 8601 timestamp, UTC")


class JobStatusResponse(BaseModel):
    """Small polling payload: counts and stage names only, never results."""

    id: str
    state: JobState
    documents_total: int
    documents_completed: int = Field(
        description="Documents that finished, whether they completed or failed"
    )
    created_at: str
    updated_at: str
    expires_at: str | None = Field(
        default=None, description="Set once the job is terminal; state is dropped after this"
    )
    error: JobErrorPayload | None = Field(
        default=None, description="Set only when the whole job failed"
    )
    documents: list[DocumentStatusPayload]


class JobResultsResponse(BaseModel):
    id: str
    state: JobState
    results: list[DocumentResult] = Field(description="One result per document, in upload order")


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable code the frontend can switch on")
    message: str = Field(description="Human-readable explanation, safe to display")


class ErrorResponse(BaseModel):
    error: ErrorDetail
