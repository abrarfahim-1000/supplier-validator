"""Match a quote to its purchase request line and compute the differences.

Matching is exact: item code first, then exact description. There is no fuzzy matching and
no "closest line" fallback. No match, or more than one match, is reported as an issue and
the graph routes the document to a person.

Two print layouts are handled without loosening that rule. Quotations often print the item
code and the description in one column (`<code> <description>`), and the model may keep the
code in the description, drop it, or put the whole cell in `item_code`. All three compare
equal to the purchase request only after that leading code is removed, and the remainder must
still match a description exactly.
"""

from __future__ import annotations

import re
from decimal import Decimal

from checker.normalize import collapse
from checker.schemas import (
    ComparisonIssue,
    LineComparison,
    MatchMethod,
    PurchaseRequest,
    PurchaseRequestComparison,
    PurchaseRequestLine,
    QuoteLineItem,
)

_LEADING_CODE = re.compile(r"^(?P<code>[a-z0-9][a-z0-9._/-]*)\s*(?:[:.\-\u2013]\s*)?(?P<rest>.+)$")


def normalize_key(text: str) -> str:
    return collapse(text).casefold()


def _without_code_prefix(text: str, code: str) -> str | None:
    """`a cotton twill fabric` with code `a` gives `cotton twill fabric`, else None."""
    match = _LEADING_CODE.match(text)
    if match is None or match.group("code") != code:
        return None
    return match.group("rest")


def _percent_difference(quoted: Decimal, reference: Decimal) -> Decimal:
    if reference == 0:
        raise ValueError("purchase request reference value must not be zero")
    return (quoted - reference) / reference * Decimal(100)


def _compare(
    item: QuoteLineItem,
    request_line: PurchaseRequestLine,
    matched_by: MatchMethod,
) -> LineComparison:
    quoted_quantity = item.quantity.value
    quoted_price = item.unit_price.value
    if quoted_quantity is None or quoted_price is None:
        raise ValueError("comparison requires a usable quoted quantity and unit price")
    return LineComparison(
        matched_by=matched_by,
        item_code=request_line.item_code,
        description=request_line.description,
        request_line_text=request_line.csv_line,
        requested_quantity=request_line.quantity_requested,
        quoted_quantity=quoted_quantity,
        quantity_difference=quoted_quantity - request_line.quantity_requested,
        quantity_difference_percent=_percent_difference(
            quoted_quantity, request_line.quantity_requested
        ),
        max_unit_price=request_line.max_unit_price,
        quoted_unit_price=quoted_price,
        unit_price_difference=quoted_price - request_line.max_unit_price,
        unit_price_difference_percent=_percent_difference(
            quoted_price, request_line.max_unit_price
        ),
    )


def _match_kind(
    quote_code: str | None,
    quote_description: str | None,
    line: PurchaseRequestLine,
) -> MatchMethod | None:
    """How (and whether) this quote line identifies that purchase request line."""
    code_key = normalize_key(line.item_code)
    description_key = normalize_key(line.description)

    if quote_code is not None and quote_code == code_key:
        return MatchMethod.ITEM_CODE
    # The whole cell landed in `item_code`; it still has to equal a description exactly.
    if quote_code is not None and quote_code == description_key:
        return MatchMethod.DESCRIPTION
    if quote_description is None:
        return None
    if quote_description == description_key:
        return MatchMethod.DESCRIPTION
    if _without_code_prefix(quote_description, code_key) == description_key:
        return MatchMethod.DESCRIPTION
    return None


def match_purchase_request_line(
    item: QuoteLineItem,
    purchase_request: PurchaseRequest,
) -> PurchaseRequestComparison:
    quote_code = normalize_key(item.item_code.value or "") if item.item_code.usable else None
    quote_description = (
        normalize_key(item.description.value or "") if item.description.usable else None
    )

    hits: list[tuple[PurchaseRequestLine, MatchMethod]] = []
    for line in purchase_request.lines:
        kind = _match_kind(quote_code, quote_description, line)
        if kind is not None:
            hits.append((line, kind))

    if not hits:
        return PurchaseRequestComparison(
            issue=ComparisonIssue.NO_MATCH,
            detail="no purchase request line matches this quote by item code or description",
        )
    if len(hits) > 1:
        return PurchaseRequestComparison(
            issue=ComparisonIssue.AMBIGUOUS_MATCH,
            detail=(
                "more than one purchase request line matches this quote: "
                + ", ".join(line.item_code for line, _ in hits)
            ),
        )
    line, matched_by = hits[0]
    try:
        compared = _compare(item, line, matched_by)
    except ValueError as exc:
        return PurchaseRequestComparison(
            issue=ComparisonIssue.UNUSABLE_VALUES,
            detail=f"quote cannot be compared with the purchase request: {exc}",
        )
    return PurchaseRequestComparison(line=compared)
