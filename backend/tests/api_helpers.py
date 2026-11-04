"""Shared helpers for the API tests: settings, clients, uploads and polling."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Any

from fastapi.testclient import TestClient

from api.app import create_app
from api.models import ProgressState
from api.runner import ExtractionSetup
from api.settings import ApiSettings
from canned import SYNTHETIC_LINES, extraction_payload
from pdf_factory import make_pdf

Messages = list[dict[str, str]]
Completer = Callable[[Messages], str]

PURCHASE_REQUEST_CSV = (
    b"PR number,Item,Description,Unit,Quantity requested,Maximum unit price (BDT)\n"
    b'PR-0000-001,A,"Blue denim roll, 12 oz",piece,100,10\n'
)

OTHER_PURCHASE_REQUEST_CSV = (
    b"PR number,Item,Description,Unit,Quantity requested,Maximum unit price (BDT)\n"
    b"PR-0000-001,B,Brass eyelet 6 mm,piece,50,38\n"
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "max_pdfs": 20,
    "max_file_bytes": 5 * 1024 * 1024,
    "max_concurrent_jobs": 2,
    "job_ttl_seconds": 3600,
    "job_timeout_seconds": 600,
    "rate_limit_jobs": 100,
    "rate_limit_window_seconds": 60,
    "allowed_origins": ("http://localhost:5173",),
}


def make_settings(tmp_path: Path, **overrides: Any) -> ApiSettings:
    values: dict[str, Any] = {**DEFAULT_SETTINGS, "temp_dir_base": tmp_path / "jobs"}
    values.update(overrides)
    return ApiSettings.model_validate(values)


@contextmanager
def api_client(
    tmp_path: Path,
    *,
    complete: Completer | None = None,
    max_retries: int = 0,
    clock: Callable[[], float] | None = None,
    setup_factory: Callable[[], ExtractionSetup] | None = None,
    **overrides: Any,
) -> Iterator[TestClient]:
    """A client whose job runner uses the given canned completer. No live model is called."""
    setup = ExtractionSetup(completer=complete or payload_completer(), max_retries=max_retries)
    app = create_app(
        settings=make_settings(tmp_path, **overrides),
        setup_factory=setup_factory or (lambda: setup),
        clock=clock,
    )
    with TestClient(app) as client:
        yield client


def payload_completer(payload: dict[str, Any] | None = None) -> Completer:
    content = json.dumps(payload if payload is not None else extraction_payload())

    def complete(messages: Messages) -> str:
        return content

    return complete


def marker_completer(good_marker: str = "Synthetic Fabrics Ltd") -> Completer:
    """Valid extraction for documents whose text contains the marker, junk for the rest."""
    content = json.dumps(extraction_payload())

    def complete(messages: Messages) -> str:
        return content if good_marker in messages[-1]["content"] else "no json here"

    return complete


def blocking_completer(release: Event) -> Completer:
    content = json.dumps(extraction_payload())

    def complete(messages: Messages) -> str:
        assert release.wait(timeout=10), "the test never released the model call"
        return content

    return complete


def csv_upload(
    content: bytes = PURCHASE_REQUEST_CSV,
    *,
    name: str = "purchase-request.csv",
    content_type: str = "text/csv",
) -> tuple[str, bytes, str]:
    return (name, content, content_type)


def pdf_upload(
    content: bytes | None = None,
    *,
    name: str = "supplier-pack-01.pdf",
    content_type: str = "application/pdf",
) -> tuple[str, bytes, str]:
    return (name, content if content is not None else make_pdf(SYNTHETIC_LINES), content_type)


def other_pdf_upload(name: str = "supplier-pack-02.pdf") -> tuple[str, bytes, str]:
    return (name, make_pdf(["Second Supplier Ltd", "QUOTATION 2", "Item B"]), "application/pdf")


def create_job(
    client: TestClient,
    *,
    csv: tuple[str, bytes, str] | None = None,
    pdfs: list[tuple[str, bytes, str]] | None = None,
) -> Any:
    documents = pdfs if pdfs is not None else [pdf_upload()]
    # Repeat the field name per file: a dict value with a list does not encode as multipart.
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("purchase_request", csv or csv_upload()),
        *[("supplier_quotes", document) for document in documents],
    ]
    return client.post("/jobs", files=files)


def wait_for(
    client: TestClient,
    job_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if predicate(payload):
            return payload
        time.sleep(0.01)
    raise AssertionError(f"job never matched the condition; last payload: {payload}")


def wait_for_state(client: TestClient, job_id: str, state: str) -> dict[str, Any]:
    return wait_for(client, job_id, lambda payload: payload["state"] == state)


def wait_for_document_state(
    client: TestClient, job_id: str, state: ProgressState
) -> dict[str, Any]:
    return wait_for(
        client,
        job_id,
        lambda payload: any(document["state"] == state for document in payload["documents"]),
    )
