"""Turn raw extracted strings into typed values for the checks.

The LLM never converts units or does arithmetic. Everything here is pure code: weeks to
days, percentages to Decimals, comma-separated money. Anything ambiguous (a range, "as
agreed", relative wording, conflicting percentages) stays flagged and later routes to a
person. A snippet that does not literally appear in the document text is not trusted.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from checker.schemas import (
    ExtractedField,
    FieldStatus,
    Quote,
    QuoteLineItem,
    RawLineItem,
    RawQuote,
    RawValue,
    Terms,
)

_WHITESPACE = re.compile(r"\s+")
_PLAIN_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PERCENT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*%")
_RANGE_TIMEFRAME = re.compile(
    r"(\d+)\s*(?:to|through|and|[-\u2013\u2014])\s*(\d+)\s*(days?|weeks?|months?)",
    re.IGNORECASE,
)
_WEEKS = re.compile(r"(\d+(?:\.\d+)?)\s*weeks?", re.IGNORECASE)
_DAYS = re.compile(r"(\d+(?:\.\d+)?)\s*days?", re.IGNORECASE)
_MONTHS = re.compile(r"(\d+(?:\.\d+)?)\s*months?", re.IGNORECASE)
_RELATIVE = re.compile(
    r"\b(?:less|fewer|more|greater|earlier|later)\s+than\b",
    re.IGNORECASE,
)
_ADVANCE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(?:of\s+(?:the\s+)?(?:order|contract)\s+value\s+)?"
    r"(?:advance|down\s*payment)",
    re.IGNORECASE,
)
_ADVANCE_OF = re.compile(
    r"(?:advance|down\s*payment)(?:\s+payment)?\s*(?:of|at|is|:)\s*"
    r"(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_NO_ADVANCE = re.compile(
    r"\bno\s+(?:advance|down\s*payment)\b|\badvance[^.]{0,30}\bnone\b|\b0\s*%\s*advance",
    re.IGNORECASE,
)
_PENALTY_BASIS = re.compile(r"of\s+(?:the\s+)?order\s+value", re.IGNORECASE)
_SEVEN_DAYS = Decimal(7)


@dataclass(frozen=True)
class Parsed[F]:
    value: F | None = None
    note: str | None = None


def collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def snippet_in_source(snippet: str, source_text: str) -> bool:
    """True when the snippet appears verbatim, ignoring whitespace and line wrapping."""
    return collapse(snippet) in collapse(source_text)


LOCATED_NOTE = "quote replaced with the document line that contains this value"


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def parse_money(text: str) -> Parsed[Decimal]:
    match = _PLAIN_NUMBER.search(text.replace("BDT", " ").replace("Tk.", " "))
    if match is None:
        return Parsed(None, "no amount found")
    try:
        return Parsed(_decimal(match.group(0)))
    except InvalidOperation:
        return Parsed(None, "amount is not a valid number")


def parse_percent(text: str) -> Parsed[Decimal]:
    values = {_decimal(match.group(1)) for match in _PERCENT.finditer(text)}
    if not values:
        return Parsed(None, "no percentage found")
    if len(values) > 1:
        return Parsed(None, "more than one percentage value is stated")
    return Parsed(next(iter(values)))


def parse_days(text: str) -> Parsed[Decimal]:
    cleaned = collapse(text)
    if _RELATIVE.search(cleaned):
        return Parsed(None, "relative wording cannot be reduced to a single number of days")
    if _RANGE_TIMEFRAME.search(cleaned):
        return Parsed(None, "a range of timeframes cannot be reduced to one number of days")
    if match := _WEEKS.search(cleaned):
        return Parsed(Decimal(match.group(1)) * _SEVEN_DAYS)
    if match := _DAYS.search(cleaned):
        return Parsed(Decimal(match.group(1)))
    if match := _MONTHS.search(cleaned):
        return Parsed(None, f"month-based timeframe '{match.group(0)}' is not converted to days")
    if "as agreed" in cleaned.casefold():
        return Parsed(None, "timeframe is 'as agreed', which is not a number of days")
    return Parsed(None, "no number of days or weeks found")


def parse_advance_percent(text: str) -> Parsed[Decimal]:
    if _NO_ADVANCE.search(text):
        return Parsed(Decimal(0))
    values = {
        _decimal(match.group(1))
        for pattern in (_ADVANCE, _ADVANCE_OF)
        for match in pattern.finditer(text)
    }
    if not values:
        bare = {_decimal(match.group(1)) for match in _PERCENT.finditer(text)}
        if len(bare) == 1:
            return Parsed(next(iter(bare)))
        if len(bare) > 1:
            return Parsed(None, "conflicting advance percentages are stated")
        return Parsed(None, "no advance percentage found")
    if len(values) > 1:
        return Parsed(None, "conflicting advance percentages are stated")
    return Parsed(next(iter(values)))


def parse_penalty_percent(text: str) -> Parsed[Decimal]:
    return parse_percent(text)


def parse_penalty_basis(text: str) -> Parsed[bool]:
    return Parsed(_PENALTY_BASIS.search(text) is not None)


def parse_text(text: str) -> Parsed[str]:
    cleaned = collapse(text)
    if not cleaned:
        return Parsed(None, "value is empty")
    return Parsed(cleaned)


def locate_unique_line(value: str, source_text: str) -> str | None:
    """The one printed line that contains `value` verbatim, or None.

    Small models often rebuild a label instead of copying the line: for a line that prints
    "Supplier TIN: ... BIN: ..." the quote comes back as "Supplier BIN: ...". The quote is
    then not verbatim, but the value itself is still checked against the document: it has to
    appear on exactly one line, and that line becomes the evidence. A value that appears
    nowhere, or on several lines, is not located at all.
    """
    needle = collapse(value)
    if not needle:
        return None
    matches = [line.strip() for line in source_text.splitlines() if needle in collapse(line)]
    return matches[0] if len(matches) == 1 else None


def build_field[F](
    raw: RawValue,
    parser: Callable[[str], Parsed[F]],
    source_text: str,
) -> ExtractedField[F]:
    """Validate provenance, then parse. Every failure keeps the field unusable."""
    if raw.value is None or not raw.value.strip():
        return ExtractedField(status=FieldStatus.MISSING, note="not stated in the document")
    if raw.source is None or not raw.source.strip():
        return ExtractedField(status=FieldStatus.UNVERIFIED, note="no source snippet supplied")

    snippet = raw.source
    note: str | None = None
    if not snippet_in_source(snippet, source_text):
        located = locate_unique_line(raw.value, source_text)
        if located is None:
            return ExtractedField(
                status=FieldStatus.UNVERIFIED,
                snippet=raw.source,
                note="source snippet does not appear in the document text",
            )
        snippet = located
        note = LOCATED_NOTE

    parsed = parser(raw.value)
    if parsed.value is None:
        return ExtractedField(
            status=FieldStatus.AMBIGUOUS,
            snippet=snippet,
            note=parsed.note,
        )
    value = parsed.value
    return ExtractedField(value=value, snippet=snippet, status=FieldStatus.OK, note=note)


def normalize_line_item(raw: RawLineItem, source_text: str) -> QuoteLineItem:
    return QuoteLineItem(
        item_code=build_field(raw.item_code, parse_text, source_text),
        description=build_field(raw.description, parse_text, source_text),
        unit=build_field(raw.unit, parse_text, source_text),
        quantity=build_field(raw.quantity, parse_money, source_text),
        unit_price=build_field(raw.unit_price, parse_money, source_text),
        line_total=build_field(raw.line_total, parse_money, source_text),
    )


def normalize_quote(raw: RawQuote, source_text: str) -> Quote:
    terms = raw.terms
    return Quote(
        supplier_name=build_field(raw.supplier_name, parse_text, source_text),
        quotation_number=build_field(raw.quotation_number, parse_text, source_text),
        quote_date=build_field(raw.quote_date, parse_text, source_text),
        purchase_request_reference=build_field(
            raw.purchase_request_reference, parse_text, source_text
        ),
        line_items=[normalize_line_item(item, source_text) for item in raw.line_items],
        subtotal=build_field(raw.subtotal, parse_money, source_text),
        vat_statement=build_field(raw.vat_statement, parse_text, source_text),
        vat_rate=build_field(raw.vat_rate, parse_percent, source_text),
        vat_amount=build_field(raw.vat_amount, parse_money, source_text),
        total=build_field(raw.total, parse_money, source_text),
        tin=build_field(raw.tin, parse_text, source_text),
        bin=build_field(raw.bin, parse_text, source_text),
        terms=Terms(
            advance_percent=build_field(terms.advance_payment, parse_advance_percent, source_text),
            payment_days=build_field(terms.payment_days, parse_days, source_text),
            delivery_days=build_field(terms.delivery_days, parse_days, source_text),
            late_penalty_clause=build_field(terms.late_delivery_penalty, parse_text, source_text),
            penalty_percent_per_week=build_field(
                terms.late_delivery_penalty, parse_penalty_percent, source_text
            ),
            penalty_basis_order_value=build_field(
                RawValue(
                    value=terms.late_delivery_penalty.source or terms.late_delivery_penalty.value,
                    source=terms.late_delivery_penalty.source,
                ),
                parse_penalty_basis,
                source_text,
            ),
            validity_days=build_field(terms.validity_days, parse_days, source_text),
        ),
    )
