"""In-memory job state.

A job is one purchase request plus up to twenty PDFs. State lives in this process only: it is
lost on restart and expires an hour after the job finishes, so the hosted app must run a
single worker. This module is the only writer, which keeps every snapshot consistent while
the runner updates progress from a worker thread.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from api.errors import (
    JOB_FAILED,
    JOB_NOT_FOUND,
    RATE_LIMITED,
    RESULTS_NOT_READY,
    TOO_MANY_JOBS,
    ApiError,
)
from api.models import (
    DocumentStatusPayload,
    JobCreatedResponse,
    JobErrorPayload,
    JobResultsResponse,
    JobState,
    JobStatusResponse,
    ProgressState,
    StageStatusPayload,
)
from checker.schemas import DocumentResult, PurchaseRequest
from checker.stages import STAGES

TERMINAL_STATES = frozenset({JobState.COMPLETED, JobState.FAILED})
FINISHED_DOCUMENT_STATES = frozenset({ProgressState.COMPLETED, ProgressState.FAILED})


@dataclass
class JobDocument:
    id: str
    filename: str
    stored_path: Path
    state: ProgressState = ProgressState.PENDING
    stages: dict[str, ProgressState] = field(default_factory=lambda: _all_pending())


def _all_pending() -> dict[str, ProgressState]:
    return dict.fromkeys(STAGES, ProgressState.PENDING)


@dataclass(frozen=True)
class JobFailure:
    code: str
    message: str


@dataclass
class Job:
    id: str
    work_dir: Path
    purchase_request: PurchaseRequest
    documents: list[JobDocument]
    state: JobState = JobState.QUEUED
    created_at: float = 0.0
    updated_at: float = 0.0
    completed_at: float | None = None
    expires_at: float | None = None
    error: JobFailure | None = None
    results: dict[str, DocumentResult] = field(default_factory=dict)


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


class JobStore:
    """Job records plus admission control, guarded by one lock."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_concurrent: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_concurrent = max_concurrent
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._active = 0

    # --- admission ----------------------------------------------------------------

    def ensure_capacity(self) -> None:
        """Cheap pre-check before any bytes are written. `add` re-checks atomically."""
        with self._lock:
            self._purge_locked()
            if self._active >= self._max_concurrent:
                raise ApiError(
                    429,
                    TOO_MANY_JOBS,
                    "the server is already checking the maximum number of jobs;"
                    " try again in a moment",
                )

    def add(self, job: Job) -> JobCreatedResponse:
        with self._lock:
            self._purge_locked()
            if self._active >= self._max_concurrent:
                raise ApiError(429, TOO_MANY_JOBS, "the server is busy; try again in a moment")
            now = self._clock()
            job.created_at = now
            job.updated_at = now
            self._jobs[job.id] = job
            self._active += 1
            return JobCreatedResponse(
                id=job.id,
                state=job.state,
                documents_total=len(job.documents),
                created_at=_iso(now) or "",
            )

    # --- reads --------------------------------------------------------------------

    def status(self, job_id: str) -> JobStatusResponse:
        with self._lock:
            job = self._require_locked(job_id)
            return JobStatusResponse(
                id=job.id,
                state=job.state,
                documents_total=len(job.documents),
                documents_completed=sum(
                    1 for document in job.documents if document.state in FINISHED_DOCUMENT_STATES
                ),
                created_at=_iso(job.created_at) or "",
                updated_at=_iso(job.updated_at) or "",
                expires_at=_iso(job.expires_at),
                error=(
                    JobErrorPayload(code=job.error.code, message=job.error.message)
                    if job.error is not None
                    else None
                ),
                documents=[
                    DocumentStatusPayload(
                        id=document.id,
                        filename=document.filename,
                        state=document.state,
                        stages=[
                            StageStatusPayload(name=name, status=status)
                            for name, status in document.stages.items()
                        ],
                    )
                    for document in job.documents
                ],
            )

    def results(self, job_id: str) -> JobResultsResponse:
        with self._lock:
            job = self._require_locked(job_id)
            if job.state is JobState.FAILED:
                message = job.error.message if job.error else "the job failed"
                raise ApiError(409, JOB_FAILED, message)
            if job.state is not JobState.COMPLETED:
                raise ApiError(
                    409, RESULTS_NOT_READY, "results are available once the job is completed"
                )
            return JobResultsResponse(
                id=job.id,
                state=job.state,
                results=[
                    job.results[document.id]
                    for document in job.documents
                    if document.id in job.results
                ],
            )

    # --- runner updates -----------------------------------------------------------

    def mark_processing(self, job_id: str) -> None:
        with self._lock:
            job = self._lookup_locked(job_id)
            if job is None or job.state in TERMINAL_STATES:
                return
            job.state = JobState.PROCESSING
            job.updated_at = self._clock()

    def document_started(self, job_id: str, document_id: str) -> None:
        with self._lock:
            document = self._document_locked(job_id, document_id)
            if document is None:
                return
            document.state = ProgressState.PROCESSING
            self._touch_locked(job_id)

    def stage_changed(
        self, job_id: str, document_id: str, stage: str, status: ProgressState
    ) -> None:
        with self._lock:
            document = self._document_locked(job_id, document_id)
            if document is None or stage not in document.stages:
                return
            document.stages[stage] = status
            self._touch_locked(job_id)

    def record_result(
        self,
        job_id: str,
        document_id: str,
        result: DocumentResult,
        *,
        state: ProgressState,
        fail_pending_stages: bool = False,
    ) -> None:
        with self._lock:
            document = self._document_locked(job_id, document_id)
            if document is None:
                return
            document.state = state
            if fail_pending_stages:
                for name, status in document.stages.items():
                    if status is not ProgressState.COMPLETED:
                        document.stages[name] = ProgressState.FAILED
            self._job_locked(job_id).results[document_id] = result
            self._touch_locked(job_id)

    def complete_job(self, job_id: str) -> None:
        with self._lock:
            job = self._lookup_locked(job_id)
            if job is None or job.state is JobState.FAILED:
                return
            job.state = JobState.COMPLETED
            self._finish_locked(job)

    def fail_job(self, job_id: str, *, code: str, message: str) -> None:
        with self._lock:
            job = self._lookup_locked(job_id)
            if job is None:
                return
            job.state = JobState.FAILED
            job.error = JobFailure(code=code, message=message)
            for document in job.documents:
                if document.state in FINISHED_DOCUMENT_STATES:
                    continue
                document.state = ProgressState.FAILED
                for name, status in document.stages.items():
                    if status is not ProgressState.COMPLETED:
                        document.stages[name] = ProgressState.FAILED
            self._finish_locked(job)

    # --- internals ----------------------------------------------------------------

    def _job_locked(self, job_id: str) -> Job:
        job = self._jobs[job_id]
        return job

    def _lookup_locked(self, job_id: str) -> Job | None:
        self._purge_locked()
        return self._jobs.get(job_id)

    def _require_locked(self, job_id: str) -> Job:
        job = self._lookup_locked(job_id)
        if job is None:
            raise ApiError(
                404, JOB_NOT_FOUND, "this job is unknown or has expired; start a new run"
            )
        return job

    def _document_locked(self, job_id: str, document_id: str) -> JobDocument | None:
        job = self._lookup_locked(job_id)
        if job is None:
            return None
        for document in job.documents:
            if document.id == document_id:
                return document
        return None

    def _touch_locked(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.updated_at = self._clock()

    def _finish_locked(self, job: Job) -> None:
        now = self._clock()
        job.completed_at = now
        job.updated_at = now
        job.expires_at = now + self._ttl_seconds
        self._active = max(0, self._active - 1)

    def _purge_locked(self) -> None:
        now = self._clock()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.expires_at is not None and job.expires_at <= now
        ]
        for job_id in expired:
            del self._jobs[job_id]


class ClientRateLimiter:
    """Per-client cap on job creation.

    In-process and best effort: a restart clears it, and behind a proxy every client shares
    the proxy address unless the proxy is configured to preserve the client IP.
    """

    def __init__(
        self,
        *,
        max_jobs: int,
        window_seconds: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max_jobs = max_jobs
        self._window_seconds = window_seconds
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def check(self, client: str) -> None:
        with self._lock:
            now = self._clock()
            hits = self._hits.setdefault(client, deque())
            while hits and now - hits[0] >= self._window_seconds:
                hits.popleft()
            if len(hits) >= self._max_jobs:
                raise ApiError(
                    429,
                    RATE_LIMITED,
                    "too many validation runs from this client; wait a moment and try again",
                )
            hits.append(now)
