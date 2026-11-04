from __future__ import annotations

import json
import time

import pytest

from canned import extraction_payload
from checker.config import LlmSettings
from checker.parse import (
    EMPTY_EXTRACTION,
    LLM_INVALID_OUTPUT,
    LLM_UNAVAILABLE,
    LlmError,
    LlmOutputError,
    LlmTimeout,
    ParseError,
    TransientLlmError,
    build_messages,
    call_with_deadline,
    extract_fields,
    output_skeleton,
    reasoning_body,
)
from checker.schemas import RawLineItem, RawQuote, RawTerms


def completer_returning(content: str):
    def complete(messages) -> str:
        return content

    return complete


def settings_with(**overrides) -> LlmSettings:
    values = {"base_url": "https://example.invalid/v1", "model": "test-model", "api_key": "k"}
    values.update(overrides)
    return LlmSettings.model_validate(values)


def test_reasoning_control_is_omitted_when_unset() -> None:
    assert reasoning_body(settings_with()) is None


def test_reasoning_control_is_sent_when_configured() -> None:
    body = reasoning_body(settings_with(reasoning_effort="none"))

    assert body == {"reasoning": {"effort": "none"}}


def test_a_call_is_abandoned_at_the_deadline() -> None:
    def hang() -> str:
        time.sleep(0.5)
        return "too late"

    started = time.monotonic()
    with pytest.raises(LlmTimeout):
        call_with_deadline(hang, 0.05)

    # The guard returns at the deadline; it never waits for the abandoned call.
    assert time.monotonic() - started < 0.4


def test_a_call_that_answers_in_time_returns_its_value() -> None:
    assert call_with_deadline(lambda: "ready", 1.0) == "ready"


def test_a_failure_inside_the_call_is_raised_unchanged() -> None:
    def boom() -> str:
        raise ValueError("bad answer")

    with pytest.raises(ValueError, match="bad answer"):
        call_with_deadline(boom, 1.0)


def test_canned_payload_is_valid_extraction() -> None:
    raw = extract_fields(
        "synthetic document text",
        completer_returning(json.dumps(extraction_payload())),
    )
    assert len(raw.line_items) == 1
    assert raw.line_items[0].quantity is not None
    assert raw.line_items[0].quantity.value == "100"
    assert raw.terms.payment_days is not None
    assert raw.terms.payment_days.value == "45 days"


def test_fenced_json_is_accepted() -> None:
    fenced = "```json\n" + json.dumps(extraction_payload()) + "\n```"
    raw = extract_fields("synthetic document text", completer_returning(fenced))
    assert raw.supplier_name is not None
    assert raw.supplier_name.value == "Synthetic Fabrics Ltd"


def test_json_with_leading_commentary_is_accepted() -> None:
    content = "Here is the extraction:\n" + json.dumps(extraction_payload())
    raw = extract_fields("synthetic document text", completer_returning(content))
    assert len(raw.line_items) == 1


def test_invalid_json_routes_to_a_person() -> None:
    with pytest.raises(ParseError) as excinfo:
        extract_fields("synthetic document text", completer_returning("I cannot help with that"))
    assert excinfo.value.code == LLM_INVALID_OUTPUT


def test_schema_mismatch_routes_to_a_person() -> None:
    payload = extraction_payload()
    payload["line_items"] = "one item"
    with pytest.raises(ParseError) as excinfo:
        extract_fields("synthetic document text", completer_returning(json.dumps(payload)))
    assert excinfo.value.code == LLM_INVALID_OUTPUT


def test_empty_line_items_route_to_a_person() -> None:
    payload = extraction_payload(line_items=[])
    with pytest.raises(ParseError) as excinfo:
        extract_fields("synthetic document text", completer_returning(json.dumps(payload)))
    assert excinfo.value.code == EMPTY_EXTRACTION


def test_transient_failure_is_retried_once_then_succeeds() -> None:
    calls: list[dict[str, str]] = []
    sleeps: list[float] = []
    payload = json.dumps(extraction_payload())

    def complete(messages) -> str:
        calls.append(messages)
        if len(calls) == 1:
            raise TransientLlmError("rate limited")
        return payload

    raw = extract_fields(
        "synthetic document text",
        complete,
        max_retries=2,
        sleep=sleeps.append,
    )
    assert len(calls) == 2
    assert sleeps == [1]
    assert len(raw.line_items) == 1


def test_persistent_transient_failure_gives_up_after_three_attempts() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def complete(messages) -> str:
        calls.append(1)
        raise TransientLlmError("network down")

    with pytest.raises(ParseError) as excinfo:
        extract_fields(
            "synthetic document text",
            complete,
            max_retries=2,
            sleep=sleeps.append,
        )
    assert excinfo.value.code == LLM_UNAVAILABLE
    assert len(calls) == 3
    assert sleeps == [1, 2]


def test_zero_retries_makes_a_single_attempt() -> None:
    calls: list[int] = []

    def complete(messages) -> str:
        calls.append(1)
        raise TransientLlmError("network down")

    with pytest.raises(ParseError) as excinfo:
        extract_fields("text", complete, max_retries=0, sleep=lambda _: None)
    assert excinfo.value.code == LLM_UNAVAILABLE
    assert len(calls) == 1


def test_non_transient_model_error_is_not_retried() -> None:
    calls: list[int] = []

    def complete(messages) -> str:
        calls.append(1)
        raise LlmError("HTTP 401")

    with pytest.raises(ParseError) as excinfo:
        extract_fields("text", complete, max_retries=2, sleep=lambda _: None)
    assert excinfo.value.code == LLM_INVALID_OUTPUT
    assert len(calls) == 1


def test_skeleton_keys_match_the_schema() -> None:
    skeleton = output_skeleton()
    assert set(skeleton) == set(RawQuote.model_fields)
    assert set(skeleton["line_items"][0]) == set(RawLineItem.model_fields)
    assert set(skeleton["terms"]) == set(RawTerms.model_fields)


def test_prompt_marks_the_document_as_data() -> None:
    messages = build_messages("Supplier: Synthetic Fabrics Ltd")
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "untrusted data" in messages[0]["content"]
    assert "<<<DOCUMENT" in messages[1]["content"]
    assert "DOCUMENT>>>" in messages[1]["content"]
    assert "Synthetic Fabrics Ltd" in messages[1]["content"]


def test_prompt_shows_a_whole_line_source_example() -> None:
    messages = build_messages("Widget, 10 cm")
    system = messages[0]["content"]
    assert "whole printed line" in system
    # The worked example must show the VAT line quoted with its rate, because the model
    # tends to shorten that line and the shortened version is no longer verbatim.
    assert '"VAT 15% 1,500.00"' in system
    assert '"value": "1,500.00"' in system


def test_json_object_without_braces_is_rejected() -> None:
    from checker.parse import _json_object

    with pytest.raises(LlmOutputError):
        _json_object("no object here")


def test_null_values_are_allowed_for_absent_fields() -> None:
    payload = extraction_payload()
    payload["tin"] = {"value": None, "source": None}
    payload["bin"] = {"value": None, "source": None}
    raw = extract_fields("synthetic document text", completer_returning(json.dumps(payload)))
    assert raw.tin.value is None
    assert raw.bin.value is None
