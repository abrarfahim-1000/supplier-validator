"""Run a job's documents and publish progress.

Sequential by design: free-tier model endpoints rate-limit, so documents are checked one at
a time. Each document is isolated, so one failure becomes that document's needs-person
result and the rest continue. Only a missing model configuration fails the whole job. The
per-job deadline and the temporary directory are handled on every path, including failure.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from api.errors import CONFIGURATION_ERROR, INTERNAL_ERROR
from api.jobs import Job, JobDocument, JobStore
from api.models import ProgressState
from api.settings import ApiSettings
from checker.config import ConfigError, load_llm_settings
from checker.schemas import Decision, DocumentResult, Reason
from checker.stages import (
    STAGE_COMPLETED,
    STAGE_FAILED,
    STAGE_PROCESSING,
)

if TYPE_CHECKING:
    from checker.rules import RuleSet

logger = logging.getLogger(__name__)

Messages = list[dict[str, str]]
Completer = Callable[[Messages], str]

WORK_DIR_PREFIX = "sdc-"
DOCUMENT_ERROR = "EDGE-DOCUMENT-ERROR"
JOB_TIMEOUT = "EDGE-JOB-TIMEOUT"

_STAGE_STATES = {
    STAGE_PROCESSING: ProgressState.PROCESSING,
    STAGE_COMPLETED: ProgressState.COMPLETED,
    STAGE_FAILED: ProgressState.FAILED,
}


@dataclass(frozen=True)
class ExtractionSetup:
    """What one job needs in order to call the model."""

    completer: Completer
    max_retries: int


def default_extraction_setup() -> ExtractionSetup:
    settings = load_llm_settings()
    from checker.parse import build_completer

    return ExtractionSetup(completer=build_completer(settings), max_retries=settings.max_retries)


class Runner(Protocol):
    def submit(self, job: Job) -> None: ...

    def shutdown(self) -> None: ...


def make_work_dir(base: Path, job_id: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{WORK_DIR_PREFIX}{job_id}-", dir=base))


def cleanup_stale_work_dirs(base: Path) -> None:
    """Delete job directories a previous process left behind. The filesystem is ephemeral."""
    if not base.is_dir():
        return
    for path in base.iterdir():
        if path.is_dir() and path.name.startswith(WORK_DIR_PREFIX):
            shutil.rmtree(path, ignore_errors=True)


class DocumentJobRunner:
    def __init__(
        self,
        *,
        store: JobStore,
        rules: RuleSet,
        settings: ApiSettings,
        setup_factory: Callable[[], ExtractionSetup] = default_extraction_setup,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._store = store
        self._rules = rules
        self._settings = settings
        self._setup_factory = setup_factory
        self._monotonic = monotonic or time.monotonic
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_jobs, thread_name_prefix="sdc-job"
        )

    def submit(self, job: Job) -> None:
        self._executor.submit(self.run, job)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def run(self, job: Job) -> None:
        """Check every document in order. Synchronous; `submit` is the threaded entry."""
        try:
            self._store.mark_processing(job.id)
            try:
                setup = self._setup_factory()
            except ConfigError as exc:
                logger.error("job %s has no usable model configuration", job.id)
                self._store.fail_job(job.id, code=CONFIGURATION_ERROR, message=str(exc))
                return

            deadline = self._monotonic() + self._settings.job_timeout_seconds
            for document in job.documents:
                if self._monotonic() >= deadline:
                    self._store.record_result(
                        job.id,
                        document.id,
                        _timeout_result(document),
                        state=ProgressState.FAILED,
                        fail_pending_stages=True,
                    )
                    self._unlink(document.stored_path)
                    continue
                self._run_document(job, document, setup)
            self._store.complete_job(job.id)
        except Exception as exc:
            # A job always has to reach a terminal state: one left mid-flight would hold an
            # admission slot until the process restarts.
            logger.error("job %s crashed: %s", job.id, type(exc).__name__)
            self._store.fail_job(
                job.id,
                code=INTERNAL_ERROR,
                message="the job could not be completed; start a new run",
            )
        finally:
            shutil.rmtree(job.work_dir, ignore_errors=True)

    def _run_document(self, job: Job, document: JobDocument, setup: ExtractionSetup) -> None:
        self._store.document_started(job.id, document.id)
        try:
            from checker.graph import run_document

            result = run_document(
                pdf_path=document.stored_path,
                document_id=document.id,
                purchase_request=job.purchase_request,
                rules=self._rules,
                complete=setup.completer,
                max_retries=setup.max_retries,
                on_stage=lambda stage, status: self._on_stage(job.id, document.id, stage, status),
                source_filename=document.filename,
            )
        except Exception as exc:
            # The documented isolation boundary: one broken document must not take the job
            # down, and a graph wiring bug is a document failure too. The cause is logged by
            # type only, so document text and extracted values never reach the log.
            logger.error(
                "document %s in job %s failed: %s", document.id, job.id, type(exc).__name__
            )
            self._store.record_result(
                job.id,
                document.id,
                _failure_result(
                    document,
                    DOCUMENT_ERROR,
                    "the document could not be processed; a person must check it",
                ),
                state=ProgressState.FAILED,
                fail_pending_stages=True,
            )
        else:
            state = ProgressState.FAILED if result.processing_failure else ProgressState.COMPLETED
            self._store.record_result(job.id, document.id, result, state=state)
        finally:
            # The PDF is only needed while its document runs.
            self._unlink(document.stored_path)

    def _on_stage(self, job_id: str, document_id: str, stage: str, status: str) -> None:
        state = _STAGE_STATES.get(status)
        if state is None:
            logger.warning("unknown stage status %r reported for job %s", status, job_id)
            return
        self._store.stage_changed(job_id, document_id, stage, state)

    @staticmethod
    def _unlink(path: Path) -> None:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _failure_result(document: JobDocument, code: str, detail: str) -> DocumentResult:
    return DocumentResult(
        document_id=document.id,
        source_filename=document.filename,
        decision=Decision.NEEDS_PERSON,
        reasons=[
            Reason(
                code=code,
                rule_id=None,
                title="Document could not be checked",
                detail=detail,
            )
        ],
        checks=[],
        processing_failure=True,
        failure_detail=detail,
    )


def _timeout_result(document: JobDocument) -> DocumentResult:
    return _failure_result(
        document,
        JOB_TIMEOUT,
        "the job ran out of time before this document was checked;"
        " run it again or check it by hand",
    )
