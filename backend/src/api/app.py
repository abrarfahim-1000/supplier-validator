"""The hosted API: a thin layer over the per-document graph.

No business logic lives here. Routes validate uploads, register a job and expose the state
the runner writes; every comparison, threshold and decision comes from `checker`. The flow
is create-then-poll because one run is a purchase request plus up to twenty PDFs.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from api.errors import INTERNAL_ERROR, ApiError, install_error_handlers
from api.jobs import ClientRateLimiter, Job, JobDocument, JobStore
from api.models import (
    ErrorResponse,
    HealthResponse,
    JobCreatedResponse,
    JobResultsResponse,
    JobStatusResponse,
)
from api.runner import (
    DocumentJobRunner,
    ExtractionSetup,
    cleanup_stale_work_dirs,
    default_extraction_setup,
    make_work_dir,
)
from api.settings import ApiSettings
from api.uploads import StagedJob, stage_job
from checker import __version__
from checker.config import load_env_file

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Invalid uploads or request"},
    404: {"model": ErrorResponse, "description": "Unknown or expired job"},
    409: {"model": ErrorResponse, "description": "Results are not available yet"},
    413: {"model": ErrorResponse, "description": "A file is too large"},
    429: {"model": ErrorResponse, "description": "Too many jobs, or rate limited"},
    500: {"model": ErrorResponse, "description": "The server could not complete the request"},
}


def _client_key(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _build_job(job_id: str, work_dir: Path, staged: StagedJob) -> Job:
    documents = [
        JobDocument(
            id=f"doc-{index:02d}",
            filename=file.original_name,
            stored_path=file.path,
        )
        for index, file in enumerate(staged.documents, start=1)
    ]
    return Job(
        id=job_id,
        work_dir=work_dir,
        purchase_request=staged.purchase_request,
        documents=documents,
    )


def create_app(
    *,
    settings: ApiSettings | None = None,
    setup_factory: Callable[[], ExtractionSetup] = default_extraction_setup,
    clock: Callable[[], float] | None = None,
) -> FastAPI:
    """Build the app. `clock` exists so tests can advance time without sleeping."""
    load_env_file()
    api_settings = settings or ApiSettings.from_env()
    store = JobStore(
        ttl_seconds=api_settings.job_ttl_seconds,
        max_concurrent=api_settings.max_concurrent_jobs,
        clock=clock,
    )
    limiter = ClientRateLimiter(
        max_jobs=api_settings.rate_limit_jobs,
        window_seconds=api_settings.rate_limit_window_seconds,
        clock=clock,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Rules are required: without them nothing can be decided, so fail fast on startup.
        from checker.rules import load_rules

        rules = load_rules()
        cleanup_stale_work_dirs(api_settings.temp_dir_base)
        runner = DocumentJobRunner(
            store=store,
            rules=rules,
            settings=api_settings,
            setup_factory=setup_factory,
        )
        application.state.runner = runner
        try:
            yield
        finally:
            runner.shutdown()
            application.state.runner = None

    app = FastAPI(
        title="Supplier Document Checker",
        version=__version__,
        summary="Deterministic checks for supplier quotations against a purchase request.",
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
    )
    app.state.settings = api_settings
    app.state.store = store
    app.state.limiter = limiter
    app.state.runner = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(api_settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        max_age=600,
    )
    install_error_handlers(app)

    def active_runner() -> DocumentJobRunner:
        runner = cast("DocumentJobRunner | None", app.state.runner)
        if runner is None:
            raise ApiError(503, INTERNAL_ERROR, "the server is still starting up")
        return runner

    @app.get("/health", response_model=HealthResponse, summary="Liveness check")
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    @app.post(
        "/jobs",
        response_model=JobCreatedResponse,
        status_code=201,
        summary="Create a validation job",
        description=(
            "Accepts one purchase request CSV or JSON file and one or more supplier quotation PDFs."
            " Returns immediately; processing continues in the background."
        ),
    )
    async def create_job(
        request: Request,
        purchase_request: Annotated[
            UploadFile, File(description="Company purchase request, one CSV or JSON file")
        ],
        supplier_quotes: Annotated[
            list[UploadFile] | None,
            File(description="Supplier quotation PDFs, up to the configured cap"),
        ] = None,
    ) -> JobCreatedResponse:
        limiter.check(_client_key(request))
        store.ensure_capacity()

        job_id = uuid.uuid4().hex
        work_dir = make_work_dir(api_settings.temp_dir_base, job_id)
        keep = False
        try:
            staged = await stage_job(
                work_dir=work_dir,
                purchase_request=purchase_request,
                supplier_quotes=supplier_quotes or [],
                settings=api_settings,
            )
            job = _build_job(job_id, work_dir, staged)
            created = store.add(job)
            keep = True
        finally:
            if not keep:
                shutil.rmtree(work_dir, ignore_errors=True)

        # `job` is bound here: every failure above raises out of this function.
        try:
            active_runner().submit(job)
        except RuntimeError as exc:
            message = "the server stopped before this job could start"
            store.fail_job(job.id, code=INTERNAL_ERROR, message=message)
            raise ApiError(503, INTERNAL_ERROR, message) from exc
        return created

    @app.get(
        "/jobs/{job_id}",
        response_model=JobStatusResponse,
        summary="Poll job progress",
        description="Small payload: overall state, counts and per-document stage statuses.",
    )
    async def get_job(job_id: str) -> JobStatusResponse:
        return store.status(job_id)

    @app.get(
        "/jobs/{job_id}/results",
        response_model=JobResultsResponse,
        summary="Read job results",
        description="One decision per document. Only available once the job is completed.",
    )
    async def get_job_results(job_id: str) -> JobResultsResponse:
        return store.results(job_id)

    return app
