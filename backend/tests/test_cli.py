from __future__ import annotations

import json
from pathlib import Path

from canned import SYNTHETIC_LINES, extraction_payload
from checker.cli import format_result, main
from checker.schemas import Decision, DocumentResult, Reason
from pdf_factory import write_pdf

PURCHASE_REQUEST = (
    "PR number,Item,Description,Unit,Quantity requested,Maximum unit price (BDT)\n"
    'PR-0000-001,A,"Blue denim roll, 12 oz",metre,100,10.00\n'
)


def payload_completer(payload: dict) -> object:
    content = json.dumps(payload)

    def complete(messages) -> str:
        return content

    return complete


def write_document(path: Path) -> None:
    write_pdf(path, SYNTHETIC_LINES)


def test_cli_runs_each_document_and_prints_the_decision(tmp_path, capsys) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "purchase-request.csv").write_text(PURCHASE_REQUEST, encoding="utf-8")
    write_document(data_dir / "supplier-pack-01.pdf")

    exit_code = main(
        ["--data-dir", str(data_dir)],
        completer=payload_completer(extraction_payload()),  # type: ignore[arg-type]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[1/1] supplier-pack-01.pdf: APPROVE" in output
    assert "1 document: APPROVE 1, REJECT 0, NEEDS_PERSON 0" in output


def test_cli_without_documents_is_a_setup_error(tmp_path, capsys) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    exit_code = main(
        ["--data-dir", str(data_dir)],
        completer=payload_completer(extraction_payload()),  # type: ignore[arg-type]
    )

    assert exit_code == 2
    assert "no PDF documents" in capsys.readouterr().err


def test_cli_without_a_purchase_request_is_a_setup_error(tmp_path, capsys) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_document(data_dir / "supplier-pack-01.pdf")

    exit_code = main(
        ["--data-dir", str(data_dir)],
        completer=payload_completer(extraction_payload()),  # type: ignore[arg-type]
    )

    assert exit_code == 2
    assert "purchase-request.csv" in capsys.readouterr().err


def test_format_result_shows_the_rule_id_and_detail() -> None:
    result = DocumentResult(
        document_id="doc-1",
        source_filename="supplier.pdf",
        decision=Decision.REJECT,
        reasons=[
            Reason(
                code="REJ-02",
                rule_id="REJ-02",
                title="Advance payment is more than 20%.",
                detail="advance payment is 40.0%, more than 20%",
            )
        ],
        checks=[],
    )

    text = format_result(result)

    assert text.startswith("supplier.pdf: REJECT")
    assert (
        "[REJ-02] Advance payment is more than 20%.: advance payment is 40.0%, more than 20%"
        in text
    )


def test_format_result_says_when_nothing_triggered() -> None:
    result = DocumentResult(
        document_id="doc-1",
        source_filename="supplier.pdf",
        decision=Decision.APPROVE,
        reasons=[],
        checks=[],
    )

    assert format_result(result).endswith("no rule triggered")
