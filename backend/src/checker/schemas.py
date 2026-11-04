"""Domain models shared by extraction, normalization, checks and decisions.

Extraction fills :class:`RawQuote` with raw strings and a source snippet per field.
:mod:`checker.normalize` turns that into :class:`Quote`, which carries parsed `Decimal`
values and a status for every field. Checks only ever read the normalized model, so no
comparison or threshold runs inside an LLM prompt.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _decimal_to_str(value: Decimal) -> str:
    """Serialize Decimals as plain strings; JSON must never carry a float."""
    return format(value, "f")


Money = Annotated[
    Decimal,
    PlainSerializer(_decimal_to_str, return_type=str, when_used="json"),
]


class Severity(StrEnum):
    REJECT = "reject"
    NEEDS_PERSON = "needs_person"


class FieldStatus(StrEnum):
    """Why a field can or cannot be used by a rule."""

    OK = "ok"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    UNVERIFIED = "unverified"


class CheckStatus(StrEnum):
    PASS = "pass"
    NEEDS_PERSON = "needs_person"
    REJECT = "reject"


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    NEEDS_PERSON = "needs_person"


class EvidenceSource(StrEnum):
    SUPPLIER_DOCUMENT = "supplier_document"
    PURCHASE_REQUEST = "purchase_request"


class MatchMethod(StrEnum):
    ITEM_CODE = "item_code"
    DESCRIPTION = "description"


class ComparisonIssue(StrEnum):
    NONE = "none"
    NO_MATCH = "no_match"
    AMBIGUOUS_MATCH = "ambiguous_match"
    UNUSABLE_VALUES = "unusable_values"
    MULTIPLE_LINE_ITEMS = "multiple_line_items"


class ExtractedField[T](BaseModel):
    """A value with the verbatim snippet it came from and a usability status."""

    model_config = ConfigDict(frozen=True)

    value: T | None = None
    snippet: str | None = None
    status: FieldStatus = FieldStatus.MISSING
    note: str | None = None

    @property
    def usable(self) -> bool:
        return self.status is FieldStatus.OK and self.value is not None


# --- Raw extraction (LLM output, validated before normalization) -------------------------


class RawValue(BaseModel):
    """A value exactly as written, plus the verbatim source text it came from."""

    model_config = ConfigDict(frozen=True)

    value: str | None = None
    source: str | None = None


class RawLineItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_code: RawValue = Field(default_factory=RawValue)
    description: RawValue = Field(default_factory=RawValue)
    unit: RawValue = Field(default_factory=RawValue)
    quantity: RawValue = Field(default_factory=RawValue)
    unit_price: RawValue = Field(default_factory=RawValue)
    line_total: RawValue = Field(default_factory=RawValue)


class RawTerms(BaseModel):
    model_config = ConfigDict(frozen=True)

    advance_payment: RawValue = Field(default_factory=RawValue)
    payment_days: RawValue = Field(default_factory=RawValue)
    delivery_days: RawValue = Field(default_factory=RawValue)
    late_delivery_penalty: RawValue = Field(default_factory=RawValue)
    validity_days: RawValue = Field(default_factory=RawValue)


class RawQuote(BaseModel):
    model_config = ConfigDict(frozen=True)

    supplier_name: RawValue = Field(default_factory=RawValue)
    quotation_number: RawValue = Field(default_factory=RawValue)
    quote_date: RawValue = Field(default_factory=RawValue)
    purchase_request_reference: RawValue = Field(default_factory=RawValue)
    line_items: list[RawLineItem] = Field(default_factory=list)
    subtotal: RawValue = Field(default_factory=RawValue)
    vat_statement: RawValue = Field(default_factory=RawValue)
    vat_rate: RawValue = Field(default_factory=RawValue)
    vat_amount: RawValue = Field(default_factory=RawValue)
    total: RawValue = Field(default_factory=RawValue)
    tin: RawValue = Field(default_factory=RawValue)
    bin: RawValue = Field(default_factory=RawValue)
    terms: RawTerms = Field(default_factory=RawTerms)


# --- Normalized quote -------------------------------------------------------------------


class QuoteLineItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_code: ExtractedField[str]
    description: ExtractedField[str]
    unit: ExtractedField[str]
    quantity: ExtractedField[Money]
    unit_price: ExtractedField[Money]
    line_total: ExtractedField[Money]


class Terms(BaseModel):
    model_config = ConfigDict(frozen=True)

    advance_percent: ExtractedField[Money]
    payment_days: ExtractedField[Money]
    delivery_days: ExtractedField[Money]
    late_penalty_clause: ExtractedField[str]
    penalty_percent_per_week: ExtractedField[Money]
    penalty_basis_order_value: ExtractedField[bool]
    validity_days: ExtractedField[Money]


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    supplier_name: ExtractedField[str]
    quotation_number: ExtractedField[str]
    quote_date: ExtractedField[str]
    purchase_request_reference: ExtractedField[str]
    line_items: list[QuoteLineItem]
    subtotal: ExtractedField[Money]
    vat_statement: ExtractedField[str]
    vat_rate: ExtractedField[Money]
    vat_amount: ExtractedField[Money]
    total: ExtractedField[Money]
    tin: ExtractedField[str]
    bin: ExtractedField[str]
    terms: Terms


# --- Purchase request and comparison ----------------------------------------------------


class PurchaseRequestLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    pr_number: str
    item_code: str
    description: str
    unit: str
    quantity_requested: Money
    max_unit_price: Money
    csv_line: str


class PurchaseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    pr_number: str
    lines: list[PurchaseRequestLine]


class LineComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    matched_by: MatchMethod
    item_code: str
    description: str
    request_line_text: str
    requested_quantity: Money
    quoted_quantity: Money
    quantity_difference: Money
    quantity_difference_percent: Money
    max_unit_price: Money
    quoted_unit_price: Money
    unit_price_difference: Money
    unit_price_difference_percent: Money


class PurchaseRequestComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    line: LineComparison | None = None
    issue: ComparisonIssue = ComparisonIssue.NONE
    detail: str | None = None


# --- Findings and decisions -------------------------------------------------------------


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: EvidenceSource
    snippet: str
    field: str | None = None


class CheckResult(BaseModel):
    """One deterministic check. Rule checks carry a rule ID; edge cases do not."""

    model_config = ConfigDict(frozen=True)

    code: str
    rule_id: str | None
    title: str
    status: CheckStatus
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)


class Reason(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    rule_id: str | None
    title: str
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)


class DecisionVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: Decision
    reasons: list[Reason]


class FieldFlag(BaseModel):
    """A field a rule depends on that is missing, ambiguous or unverified."""

    model_config = ConfigDict(frozen=True)

    code: str
    field: str
    detail: str


class DocumentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    source_filename: str
    supplier_name: str | None = None
    quotation_number: str | None = None
    decision: Decision
    reasons: list[Reason]
    checks: list[CheckResult]
    comparison: PurchaseRequestComparison = Field(default_factory=PurchaseRequestComparison)
    quote: Quote | None = None
    flags: list[FieldFlag] = Field(default_factory=list)
    processing_failure: bool = False
    failure_detail: str | None = None
