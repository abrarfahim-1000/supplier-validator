from __future__ import annotations

from decimal import Decimal

from api.errors import INTERNAL_ERROR
from api.jobs import Job, JobDocument, JobStore
from api.models import JobState, ProgressState
from api.runner import JOB_TIMEOUT, DocumentJobRunner, ExtractionSetup
from api_helpers import make_settings, payload_completer
from builders import make_pr, make_pr_line
from canned import SYNTHETIC_LINES
from checker.rules import RuleSet
from checker.schemas import Decision
from pdf_factory import write_pdf


def _purchase_request():
    return make_pr(
        make_pr_line(
            item_code="A",
            description="Blue denim roll, 12 oz",
            quantity=Decimal("100"),
            max_price=Decimal("10"),
        )
    )


def test_document_not_reached_before_the_deadline_times_out(tmp_path, rules: RuleSet) -> None:
    work_dir = tmp_path / "job"
    work_dir.mkdir()
    first = work_dir / "document-01.pdf"
    write_pdf(first, SYNTHETIC_LINES)
    second = work_dir / "document-02.pdf"
    write_pdf(second, SYNTHETIC_LINES)

    store = JobStore(ttl_seconds=60, max_concurrent=1)
    job = Job(
        id="job-1",
        work_dir=work_dir,
        purchase_request=_purchase_request(),
        documents=[
            JobDocument(id="doc-01", filename="one.pdf", stored_path=first),
            JobDocument(id="doc-02", filename="two.pdf", stored_path=second),
        ],
    )
    store.add(job)

    # The deadline is computed from the first reading, then checked before each document.
    readings = iter([0.0, 0.0, 100.0])
    runner = DocumentJobRunner(
        store=store,
        rules=rules,
        settings=make_settings(tmp_path, job_timeout_seconds=5),
        setup_factory=lambda: ExtractionSetup(completer=payload_completer(), max_retries=0),
        monotonic=lambda: next(readings),
    )
    runner.run(job)
    runner.shutdown()

    status = store.status("job-1")
    assert status.documents_completed == 2
    assert [document.state for document in status.documents] == [
        ProgressState.COMPLETED,
        ProgressState.FAILED,
    ]

    results = store.results("job-1").results
    assert results[0].decision is Decision.APPROVE
    assert results[1].decision is Decision.NEEDS_PERSON
    assert results[1].processing_failure is True
    assert results[1].reasons[0].code == JOB_TIMEOUT
    assert {stage.status for stage in status.documents[1].stages} == {ProgressState.FAILED}

    assert not work_dir.exists()
    assert not first.exists()
    assert not second.exists()


def test_a_crash_still_leaves_the_job_terminal_and_frees_the_slot(
    tmp_path, rules: RuleSet, monkeypatch
) -> None:
    work_dir = tmp_path / "job"
    work_dir.mkdir()
    document = work_dir / "document-01.pdf"
    write_pdf(document, SYNTHETIC_LINES)

    store = JobStore(ttl_seconds=60, max_concurrent=1)
    job = Job(
        id="job-2",
        work_dir=work_dir,
        purchase_request=_purchase_request(),
        documents=[JobDocument(id="doc-01", filename="one.pdf", stored_path=document)],
    )
    store.add(job)

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the store fell over")

    monkeypatch.setattr(store, "record_result", explode)
    runner = DocumentJobRunner(
        store=store,
        rules=rules,
        settings=make_settings(tmp_path),
        setup_factory=lambda: ExtractionSetup(completer=payload_completer(), max_retries=0),
    )
    runner.run(job)
    runner.shutdown()

    status = store.status("job-2")
    assert status.state is JobState.FAILED
    assert status.error is not None
    assert status.error.code == INTERNAL_ERROR
    assert not work_dir.exists()

    # The admission slot was released, so a new job can still be accepted.
    store.ensure_capacity()
