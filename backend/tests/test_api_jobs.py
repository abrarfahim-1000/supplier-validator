from __future__ import annotations

from threading import Event
from typing import Any

from api.errors import CONFIGURATION_ERROR
from api.runner import ExtractionSetup
from api_helpers import (
    OTHER_PURCHASE_REQUEST_CSV,
    api_client,
    blocking_completer,
    create_job,
    csv_upload,
    marker_completer,
    other_pdf_upload,
    payload_completer,
    pdf_upload,
    wait_for,
    wait_for_state,
)
from checker.config import ConfigError
from checker.graph import STAGE_EXTRACTION, STAGE_INGESTION


def _stage(document: dict[str, Any], name: str) -> str:
    return next(stage["status"] for stage in document["stages"] if stage["name"] == name)


def test_job_reports_real_progress_and_results(tmp_path) -> None:
    release = Event()
    with api_client(tmp_path, complete=blocking_completer(release)) as client:
        created = create_job(client).json()

        status = wait_for(
            client,
            created["id"],
            lambda payload: _stage(payload["documents"][0], STAGE_EXTRACTION) == "processing",
        )
        assert status["documents_completed"] == 0
        assert _stage(status["documents"][0], STAGE_INGESTION) == "completed"
        assert status["documents"][0]["state"] == "processing"

        early = client.get(f"/jobs/{created['id']}/results")
        assert early.status_code == 409
        assert early.json()["error"]["code"] == "results_not_ready"

        release.set()
        final = wait_for_state(client, created["id"], "completed")
        assert final["documents_total"] == 1
        assert final["documents_completed"] == 1
        assert {stage["status"] for stage in final["documents"][0]["stages"]} == {"completed"}
        assert final["expires_at"] is not None

        results = client.get(f"/jobs/{created['id']}/results")
        assert results.status_code == 200
        payload = results.json()
        assert payload["state"] == "completed"
        assert len(payload["results"]) == 1
        assert payload["results"][0]["decision"] == "approve"
        assert payload["results"][0]["checks"]


def test_unknown_job_is_not_found(tmp_path) -> None:
    with api_client(tmp_path) as client:
        status = client.get("/jobs/nope")
        results = client.get("/jobs/nope/results")

    assert status.status_code == 404
    assert status.json()["error"]["code"] == "job_not_found"
    assert results.status_code == 404
    assert results.json()["error"]["code"] == "job_not_found"


def test_job_expires_after_the_ttl(tmp_path) -> None:
    now = [1000.0]
    with api_client(tmp_path, clock=lambda: now[0], job_ttl_seconds=60) as client:
        created = create_job(client).json()
        wait_for_state(client, created["id"], "completed")

        now[0] += 61
        expired = client.get(f"/jobs/{created['id']}")

    assert expired.status_code == 404
    assert expired.json()["error"]["code"] == "job_not_found"


def test_concurrency_cap_returns_busy_then_recovers(tmp_path) -> None:
    release = Event()
    with api_client(
        tmp_path,
        complete=blocking_completer(release),
        max_concurrent_jobs=1,
    ) as client:
        first = create_job(client)
        assert first.status_code == 201

        second = create_job(client)
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "too_many_jobs"

        release.set()
        wait_for_state(client, first.json()["id"], "completed")

        third = create_job(client)
        assert third.status_code == 201
        wait_for_state(client, third.json()["id"], "completed")


def test_job_creation_is_rate_limited_per_client(tmp_path) -> None:
    with api_client(tmp_path, rate_limit_jobs=1) as client:
        first = create_job(client)
        assert first.status_code == 201

        second = create_job(client)
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "rate_limited"

        wait_for_state(client, first.json()["id"], "completed")


def test_one_failing_document_does_not_stop_the_others(tmp_path) -> None:
    with api_client(tmp_path, complete=marker_completer()) as client:
        created = create_job(client, pdfs=[pdf_upload(), other_pdf_upload()]).json()
        final = wait_for_state(client, created["id"], "completed")

        assert final["documents_total"] == 2
        assert final["documents_completed"] == 2
        good, bad = final["documents"]
        assert good["state"] == "completed"
        assert bad["state"] == "failed"
        assert _stage(good, STAGE_INGESTION) == "completed"
        assert _stage(bad, STAGE_INGESTION) == "completed"
        assert _stage(bad, STAGE_EXTRACTION) == "failed"

        results = client.get(f"/jobs/{created['id']}/results").json()["results"]
        assert results[0]["decision"] == "approve"
        assert results[0]["processing_failure"] is False
        assert results[1]["decision"] == "needs_person"
        assert results[1]["processing_failure"] is True
        assert results[1]["failure_detail"]


def test_missing_model_configuration_fails_the_job(tmp_path) -> None:
    def broken_setup() -> ExtractionSetup:
        raise ConfigError("OPENROUTER_API_KEY is not set")

    with api_client(tmp_path, setup_factory=broken_setup) as client:
        created = create_job(client).json()
        final = wait_for_state(client, created["id"], "failed")

        assert final["error"]["code"] == CONFIGURATION_ERROR
        assert "OPENROUTER_API_KEY" in final["error"]["message"]

        results = client.get(f"/jobs/{created['id']}/results")
        assert results.status_code == 409
        assert results.json()["error"]["code"] == "job_failed"


def test_unmatched_purchase_request_line_needs_a_person(tmp_path) -> None:
    with api_client(tmp_path) as client:
        created = create_job(client, csv=csv_upload(OTHER_PURCHASE_REQUEST_CSV)).json()
        wait_for_state(client, created["id"], "completed")
        result = client.get(f"/jobs/{created['id']}/results").json()["results"][0]

    assert result["decision"] == "needs_person"
    assert result["comparison"]["issue"] == "no_match"
    assert result["comparison"]["line"] is None
    assert result["processing_failure"] is False


def test_temporary_files_are_removed_when_the_job_ends(tmp_path) -> None:
    base = tmp_path / "jobs"
    with api_client(tmp_path, complete=payload_completer()) as client:
        created = create_job(client).json()
        wait_for_state(client, created["id"], "completed")
        assert list(base.iterdir()) == []
