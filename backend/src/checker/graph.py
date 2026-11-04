"""The fixed, linear per-document graph.

Five checkable stages, one conditional edge. A hard failure (unreadable PDF, model
unavailable or invalid output, no line items) routes to a terminal needs-person result.
Uncertain individual fields do not branch here; the rule checks return needs-person and
the decision module applies precedence. Nothing loops and nothing is retried in a way
that can change an outcome.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from checker.checks import run_all_checks
from checker.compare import match_purchase_request_line
from checker.config import load_llm_settings
from checker.decide import decide
from checker.extract import ExtractionError, extract_pdf_text
from checker.flags import collect_flags
from checker.normalize import normalize_quote
from checker.parse import (
    EMPTY_EXTRACTION,
    LLM_INVALID_OUTPUT,
    LLM_UNAVAILABLE,
    Completer,
    ParseError,
    build_completer,
    extract_fields,
)
from checker.rules import RuleSet
from checker.schemas import (
    CheckResult,
    ComparisonIssue,
    Decision,
    DocumentResult,
    PurchaseRequest,
    PurchaseRequestComparison,
    Quote,
    RawQuote,
    Reason,
)
from checker.stages import (
    STAGE_COMPARISON,
    STAGE_COMPLETED,
    STAGE_DECISION,
    STAGE_EXTRACTION,
    STAGE_FAILED,
    STAGE_INGESTION,
    STAGE_PROCESSING,
    STAGE_RULES,
)

StageCallback = Callable[[str, str], None]


class GraphError(RuntimeError):
    """The graph was wired or invoked incorrectly. Not a document outcome."""


class Failure(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    detail: str
    processing: bool


_FAILURE_TITLES = {
    "EDGE-UNREADABLE-PDF": "Document could not be read",
    "EDGE-NOT-A-PDF": "Uploaded file is not a PDF",
    "EDGE-PDF-NOT-FOUND": "Uploaded PDF is missing",
    LLM_UNAVAILABLE: "Extraction model unavailable",
    LLM_INVALID_OUTPUT: "Extraction output could not be validated",
    EMPTY_EXTRACTION: "No line items were extracted",
}


class DocumentState(TypedDict, total=False):
    document_id: str
    source_filename: str
    pdf_path: str
    purchase_request: PurchaseRequest
    rules: RuleSet
    source_text: str
    raw_quote: RawQuote
    quote: Quote
    comparison: PurchaseRequestComparison
    checks: list[CheckResult]
    failure: Failure
    result: DocumentResult


def _configurable(config: RunnableConfig) -> dict[str, Any]:
    value = config.get("configurable") or {}
    if not isinstance(value, dict):
        raise GraphError("config['configurable'] must be a mapping")
    return value


def _notify(config: RunnableConfig, stage: str, status: str) -> None:
    callback = _configurable(config).get("on_stage")
    if callable(callback):
        cast("StageCallback", callback)(stage, status)


def _completer(config: RunnableConfig) -> Completer:
    value = _configurable(config).get("complete")
    if not callable(value):
        raise GraphError("the graph needs an LLM completer in config['configurable']['complete']")
    return cast("Completer", value)


def _max_retries(config: RunnableConfig) -> int:
    value = _configurable(config).get("max_retries", 2)
    if not isinstance(value, int):
        raise GraphError("max_retries must be an integer")
    return value


def _ingest(state: DocumentState, config: RunnableConfig) -> dict[str, Any]:
    _notify(config, STAGE_INGESTION, STAGE_PROCESSING)
    try:
        text = extract_pdf_text(Path(state["pdf_path"]))
    except ExtractionError as exc:
        _notify(config, STAGE_INGESTION, STAGE_FAILED)
        return {"failure": Failure(code=exc.code, detail=exc.detail, processing=True)}
    _notify(config, STAGE_INGESTION, STAGE_COMPLETED)
    return {"source_text": text}


def _parse(state: DocumentState, config: RunnableConfig) -> dict[str, Any]:
    if state.get("failure") is not None:
        _notify(config, STAGE_EXTRACTION, STAGE_FAILED)
        return {}
    _notify(config, STAGE_EXTRACTION, STAGE_PROCESSING)
    try:
        raw = extract_fields(
            state["source_text"],
            _completer(config),
            max_retries=_max_retries(config),
        )
        quote = normalize_quote(raw, state["source_text"])
    except ParseError as exc:
        _notify(config, STAGE_EXTRACTION, STAGE_FAILED)
        return {
            "failure": Failure(
                code=exc.code,
                detail=exc.detail,
                processing=exc.code != EMPTY_EXTRACTION,
            )
        }
    _notify(config, STAGE_EXTRACTION, STAGE_COMPLETED)
    return {"raw_quote": raw, "quote": quote}


def _compare(state: DocumentState, config: RunnableConfig) -> dict[str, Any]:
    _notify(config, STAGE_COMPARISON, STAGE_PROCESSING)
    quote = state["quote"]
    if len(quote.line_items) != 1:
        comparison = PurchaseRequestComparison(
            issue=ComparisonIssue.MULTIPLE_LINE_ITEMS,
            detail=(
                "the quote must contain exactly one line item to compare it with the"
                f" purchase request (found {len(quote.line_items)})"
            ),
        )
    else:
        comparison = match_purchase_request_line(quote.line_items[0], state["purchase_request"])
    _notify(config, STAGE_COMPARISON, STAGE_COMPLETED)
    return {"comparison": comparison}


def _check(state: DocumentState, config: RunnableConfig) -> dict[str, Any]:
    _notify(config, STAGE_RULES, STAGE_PROCESSING)
    checks = run_all_checks(state["quote"], state["comparison"], state["rules"])
    _notify(config, STAGE_RULES, STAGE_COMPLETED)
    return {"checks": checks}


def _decide(state: DocumentState, config: RunnableConfig) -> dict[str, Any]:
    _notify(config, STAGE_DECISION, STAGE_PROCESSING)
    quote = state["quote"]
    verdict = decide(state["checks"])
    result = DocumentResult(
        document_id=state["document_id"],
        source_filename=state["source_filename"],
        supplier_name=quote.supplier_name.value,
        quotation_number=quote.quotation_number.value,
        decision=verdict.decision,
        reasons=verdict.reasons,
        checks=state["checks"],
        comparison=state["comparison"],
        quote=quote,
        flags=collect_flags(quote),
    )
    _notify(config, STAGE_DECISION, STAGE_COMPLETED)
    return {"result": result}


def _needs_person(state: DocumentState, config: RunnableConfig) -> dict[str, Any]:
    _notify(config, STAGE_DECISION, STAGE_PROCESSING)
    failure = state["failure"]
    quote = state.get("quote")
    result = DocumentResult(
        document_id=state["document_id"],
        source_filename=state["source_filename"],
        supplier_name=quote.supplier_name.value if quote else None,
        quotation_number=quote.quotation_number.value if quote else None,
        decision=Decision.NEEDS_PERSON,
        reasons=[
            Reason(
                code=failure.code,
                rule_id=None,
                title=_FAILURE_TITLES.get(failure.code, "Document could not be checked"),
                detail=failure.detail,
            )
        ],
        checks=[],
        comparison=state.get("comparison", PurchaseRequestComparison()),
        quote=quote,
        flags=collect_flags(quote) if quote else [],
        processing_failure=failure.processing,
        failure_detail=failure.detail,
    )
    _notify(config, STAGE_DECISION, STAGE_COMPLETED)
    return {"result": result}


def _route(state: DocumentState) -> str:
    return "needs_person" if state.get("failure") is not None else "continue"


def build_graph() -> Any:
    graph: StateGraph[DocumentState] = StateGraph(DocumentState)
    graph.add_node("ingest", _ingest)
    graph.add_node("parse", _parse)
    graph.add_node("compare", _compare)
    graph.add_node("check", _check)
    graph.add_node("decide", _decide)
    graph.add_node("needs_person", _needs_person)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "parse")
    graph.add_conditional_edges(
        "parse",
        _route,
        {"continue": "compare", "needs_person": "needs_person"},
    )
    graph.add_edge("compare", "check")
    graph.add_edge("check", "decide")
    graph.add_edge("decide", END)
    graph.add_edge("needs_person", END)
    return graph.compile()


def run_document(
    *,
    pdf_path: Path,
    document_id: str,
    purchase_request: PurchaseRequest,
    rules: RuleSet,
    complete: Completer | None = None,
    max_retries: int = 2,
    on_stage: StageCallback | None = None,
    source_filename: str | None = None,
) -> DocumentResult:
    completer = complete or build_completer(load_llm_settings())
    state: DocumentState = {
        "document_id": document_id,
        "source_filename": source_filename or pdf_path.name,
        "pdf_path": str(pdf_path),
        "purchase_request": purchase_request,
        "rules": rules,
    }
    config: RunnableConfig = {
        "configurable": {
            "complete": completer,
            "max_retries": max_retries,
            "on_stage": on_stage,
        }
    }
    final = build_graph().invoke(state, config=config)
    result = cast("DocumentState", final).get("result")
    if result is None:
        raise GraphError("the graph finished without a result")
    return result
