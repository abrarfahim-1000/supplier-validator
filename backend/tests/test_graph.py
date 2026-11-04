from __future__ import annotations

import json
from decimal import Decimal

import pytest

from builders import make_pr, make_pr_line
from canned import SYNTHETIC_LINES, extraction_payload, line_item
from checker.config import ConfigError
from checker.graph import (
    STAGE_COMPARISON,
    STAGE_DECISION,
    STAGE_EXTRACTION,
    STAGE_INGESTION,
    STAGE_RULES,
    run_document,
)
from checker.parse import (
    EMPTY_EXTRACTION,
    LLM_INVALID_OUTPUT,
    LLM_UNAVAILABLE,
    TransientLlmError,
)
from checker.schemas import CheckStatus, ComparisonIssue, Decision, FieldStatus
from pdf_factory import blank_pdf, write_pdf


def canned_pr():
    return make_pr(
        make_pr_line(
            item_code="A",
            description="Blue denim roll, 12 oz",
            quantity=Decimal("100"),
            max_price=Decimal("10"),
        )
    )


def payload_completer(payload: dict) -> object:
    content = json.dumps(payload)

    def complete(messages) -> str:
        return content

    return complete


def run(path, complete, rules, *, pr=None, max_retries=2, on_stage=None):
    return run_document(
        pdf_path=path,
        document_id="doc-1",
        purchase_request=pr or canned_pr(),
        rules=rules,
        complete=complete,
        max_retries=max_retries,
        on_stage=on_stage,
        source_filename="supplier.pdf",
    )


def test_clean_document_is_approved(tmp_path, rules) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)

    result = run(path, payload_completer(extraction_payload()), rules=rules)

    assert result.decision is Decision.APPROVE
    assert result.reasons == []
    assert len(result.checks) == 15
    assert result.supplier_name == "Synthetic Fabrics Ltd"
    assert result.quotation_number == "QT-TEST-001"
    assert result.processing_failure is False
    assert result.flags == []


def test_every_stage_reports_processing_then_completed(tmp_path, rules) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)
    events: list[tuple[str, str]] = []

    run(
        path,
        payload_completer(extraction_payload()),
        rules=rules,
        on_stage=lambda stage, status: events.append((stage, status)),
    )

    assert events == [
        (STAGE_INGESTION, "processing"),
        (STAGE_INGESTION, "completed"),
        (STAGE_EXTRACTION, "processing"),
        (STAGE_EXTRACTION, "completed"),
        (STAGE_COMPARISON, "processing"),
        (STAGE_COMPARISON, "completed"),
        (STAGE_RULES, "processing"),
        (STAGE_RULES, "completed"),
        (STAGE_DECISION, "processing"),
        (STAGE_DECISION, "completed"),
    ]


def test_blank_pdf_needs_a_person_without_calling_the_model(tmp_path, rules) -> None:
    path = tmp_path / "blank.pdf"
    blank_pdf(path)
    events: list[tuple[str, str]] = []

    def complete(messages) -> str:
        raise AssertionError("the model must not be called for an unreadable PDF")

    result = run(
        path,
        complete,
        rules=rules,
        on_stage=lambda stage, status: events.append((stage, status)),
    )

    assert result.decision is Decision.NEEDS_PERSON
    assert result.processing_failure is True
    assert result.failure_detail is not None
    assert result.reasons[0].code.startswith("EDGE-")
    assert events == [
        (STAGE_INGESTION, "processing"),
        (STAGE_INGESTION, "failed"),
        (STAGE_EXTRACTION, "failed"),
        (STAGE_DECISION, "processing"),
        (STAGE_DECISION, "completed"),
    ]


def test_invalid_model_output_is_a_processing_failure(tmp_path, rules) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)

    result = run(path, lambda messages: "sorry, no json", rules=rules)

    assert result.decision is Decision.NEEDS_PERSON
    assert result.processing_failure is True
    assert result.reasons[0].code == LLM_INVALID_OUTPUT
    assert result.checks == []


def test_empty_extraction_needs_a_person_without_a_processing_failure(tmp_path, rules) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)
    payload = extraction_payload(line_items=[])

    result = run(path, payload_completer(payload), rules=rules)

    assert result.decision is Decision.NEEDS_PERSON
    assert result.processing_failure is False
    assert result.reasons[0].code == EMPTY_EXTRACTION


def test_more_than_one_line_item_needs_a_person(tmp_path, rules) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)
    payload = extraction_payload(line_items=[line_item(), line_item()])

    result = run(path, payload_completer(payload), rules=rules)

    assert result.decision is Decision.NEEDS_PERSON
    assert result.processing_failure is False
    assert result.comparison.issue is ComparisonIssue.MULTIPLE_LINE_ITEMS
    edge = next(check for check in result.checks if check.code == "EDGE-MULTIPLE-LINE-ITEMS")
    assert edge.status is CheckStatus.NEEDS_PERSON
    assert edge.rule_id is None
    assert "EDGE-MULTIPLE-LINE-ITEMS" in {reason.code for reason in result.reasons}


def test_a_rebuilt_quote_is_recovered_from_the_document(tmp_path, rules) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)
    payload = extraction_payload()
    payload["line_items"][0]["unit_price"] = {
        "value": "10.00",
        "source": "the price is ten taka and no mistake",
    }

    result = run(path, payload_completer(payload), rules=rules)

    assert result.quote is not None
    unit_price = result.quote.line_items[0].unit_price
    # The value is printed on exactly one line, so that line becomes the evidence and the
    # quote failure alone does not send a clean document to a person.
    assert unit_price.status is FieldStatus.OK
    assert unit_price.snippet == "10.00"
    assert "FIELD-UNVERIFIED" not in {flag.code for flag in result.flags}


def test_an_invented_value_needs_a_person(tmp_path, rules) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)
    payload = extraction_payload()
    payload["line_items"][0]["unit_price"] = {
        "value": "77.77",
        "source": "the price is ten taka and no mistake",
    }

    result = run(path, payload_completer(payload), rules=rules)

    assert result.decision is Decision.NEEDS_PERSON
    assert "FIELD-UNVERIFIED" in {flag.code for flag in result.flags}
    assert "line_items[1].unit_price" in {flag.field for flag in result.flags}


def test_unmatched_purchase_request_line_needs_a_person(tmp_path, rules) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)
    other_pr = make_pr(
        make_pr_line(item_code="B", description="Metal zipper, 18 cm", max_price=Decimal("38"))
    )

    result = run(path, payload_completer(extraction_payload()), pr=other_pr, rules=rules)

    assert result.decision is Decision.NEEDS_PERSON
    assert result.processing_failure is False
    assert result.comparison.issue is ComparisonIssue.NO_MATCH


def test_rate_limited_model_is_retried_then_fails_the_document(tmp_path, rules) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)
    calls: list[int] = []

    def complete(messages) -> str:
        calls.append(1)
        raise TransientLlmError("rate limited")

    result = run(path, complete, rules=rules, max_retries=1)

    assert result.decision is Decision.NEEDS_PERSON
    assert result.processing_failure is True
    assert result.reasons[0].code == LLM_UNAVAILABLE
    assert len(calls) == 2


def test_missing_llm_config_is_a_setup_error(tmp_path, rules, monkeypatch) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, SYNTHETIC_LINES)
    for name in ("OPENROUTER_BASE_URL", "OPENROUTER_MODEL", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ConfigError) as excinfo:
        run_document(
            pdf_path=path,
            document_id="doc-1",
            purchase_request=canned_pr(),
            rules=rules,
        )
    assert "OPENROUTER_BASE_URL" in str(excinfo.value)
