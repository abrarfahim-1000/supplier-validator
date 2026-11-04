from __future__ import annotations

from api_helpers import (
    PURCHASE_REQUEST_CSV,
    api_client,
    create_job,
    csv_upload,
    pdf_upload,
)
from canned import SYNTHETIC_LINES
from pdf_factory import make_pdf


def test_health_reports_ok(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"]


def test_upload_without_supplier_documents_is_rejected(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = client.post("/jobs", files={"purchase_request": csv_upload()})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_supplier_documents"


def test_purchase_request_format_is_detected_from_contents(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = create_job(
            client,
            csv=csv_upload(name="request.data", content_type="application/octet-stream"),
        )

    assert response.status_code == 201


def test_purchase_request_json_is_accepted(tmp_path) -> None:
    content = (
        b'{"pr_number":"PR-0000-001","lines":[{"item_code":"A",'
        b'"description":"Blue denim roll, 12 oz","unit":"piece",'
        b'"quantity_requested":100,"max_unit_price":10.00}]}'
    )
    with api_client(tmp_path) as client:
        response = create_job(
            client,
            csv=("request.data", content, "application/octet-stream"),
        )

    assert response.status_code == 201
    assert response.json()["documents_total"] == 1


def test_malformed_purchase_request_json_is_rejected(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = create_job(
            client,
            csv=("request.data", b"{not json", "application/octet-stream"),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_purchase_request"


def test_supplier_document_format_is_detected_from_contents(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = create_job(
            client,
            pdfs=[pdf_upload(name="quote.data", content_type="application/octet-stream")],
        )

    assert response.status_code == 201


def test_supplier_document_must_start_with_the_pdf_magic(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = create_job(client, pdfs=[pdf_upload(b"not a pdf, just text")])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_pdf"


def test_too_many_documents_are_rejected(tmp_path) -> None:
    with api_client(tmp_path, max_pdfs=1) as client:
        response = create_job(client, pdfs=[pdf_upload(), pdf_upload(name="second.pdf")])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "too_many_documents"


def test_default_document_limit_is_twenty(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = create_job(client, pdfs=[pdf_upload() for _ in range(21)])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "too_many_documents"


def test_duplicate_documents_are_rejected(tmp_path) -> None:
    identical = make_pdf(SYNTHETIC_LINES)
    with api_client(tmp_path) as client:
        response = create_job(
            client,
            pdfs=[pdf_upload(identical), pdf_upload(identical, name="copy.pdf")],
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "duplicate_file"
    assert "copy.pdf" in response.json()["error"]["message"]


def test_oversized_document_is_rejected(tmp_path) -> None:
    document = make_pdf(SYNTHETIC_LINES)
    limit = len(PURCHASE_REQUEST_CSV) + 10
    assert len(document) > limit

    with api_client(tmp_path, max_file_bytes=limit) as client:
        response = create_job(client, pdfs=[pdf_upload(document)])

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_empty_document_is_rejected(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = create_job(client, pdfs=[pdf_upload(b"")])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"


def test_purchase_request_missing_columns_is_rejected(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = create_job(client, csv=csv_upload(b"PR number,Item\nPR-0000-001,A\n"))

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_purchase_request"
    assert "missing columns" in error["message"]


def test_purchase_request_must_be_utf8(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = create_job(client, csv=csv_upload(b"PR number,Item\n\xff\xfe,A\n"))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_purchase_request"


def test_error_shape_is_stable_and_leaks_nothing(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = client.get("/jobs/does-not-exist")

    body = response.json()
    assert response.status_code == 404
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert "traceback" not in response.text.lower()
    assert "Traceback" not in response.text


def test_cors_allows_only_configured_origins(tmp_path) -> None:
    with api_client(tmp_path) as client:
        allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
        blocked = client.get("/health", headers={"Origin": "http://example.invalid"})

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert blocked.headers.get("access-control-allow-origin") is None


def test_json_accepts_one_pdf_and_returns_created_job(tmp_path) -> None:
    with api_client(tmp_path) as client:
        response = create_job(client)

    assert response.status_code == 201
    body = response.json()
    assert body["documents_total"] == 1
    assert body["state"] == "queued"
    assert body["id"]
