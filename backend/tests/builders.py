"""Shared builders so check tests stay about one rule at a time."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from checker.compare import match_purchase_request_line
from checker.schemas import (
    ExtractedField,
    FieldStatus,
    PurchaseRequest,
    PurchaseRequestComparison,
    PurchaseRequestLine,
    Quote,
    QuoteLineItem,
    Terms,
)


def f(
    value: Any,
    *,
    snippet: str = "quoted source text",
    status: FieldStatus | None = None,
) -> ExtractedField[Any]:
    if status is None:
        status = FieldStatus.OK if value is not None else FieldStatus.MISSING
    return ExtractedField(
        value=value,
        snippet=snippet if value is not None else None,
        status=status,
        note=None if value is not None else "not stated in the document",
    )


def make_line_item(
    *,
    item_code: str | None = "A",
    description: str | None = "Item A",
    unit: str | None = "piece",
    quantity: Decimal | None = Decimal("100"),
    unit_price: Decimal | None = Decimal("10"),
    line_total: Decimal | None = Decimal("1000"),
) -> QuoteLineItem:
    return QuoteLineItem(
        item_code=f(item_code, snippet="Item A"),
        description=f(description, snippet="Item A"),
        unit=f(unit, snippet="piece"),
        quantity=f(quantity),
        unit_price=f(unit_price),
        line_total=f(line_total),
    )


def make_quote(
    *,
    item: QuoteLineItem | None = None,
    line_total: Decimal | None = Decimal("1000"),
    supplier_name: str | None = "Test Supplier",
    quotation_number: str | None = "QT-TEST",
    subtotal: Decimal | None = Decimal("1000"),
    vat_statement: str | None = "VAT 15%",
    vat_rate: Decimal | None = Decimal("15"),
    vat_amount: Decimal | None = Decimal("150"),
    total: Decimal | None = Decimal("1150"),
    tin: str | None = "TIN-1",
    bin_value: str | None = "BIN-1",
    advance: Decimal | None = Decimal("10"),
    payment_days: Decimal | None = Decimal("45"),
    delivery_days: Decimal | None = Decimal("25"),
    penalty_present: bool = True,
    penalty: Decimal | None = Decimal("1"),
    penalty_basis: bool | None = True,
    validity_days: Decimal | None = Decimal("45"),
    extra_items: list[QuoteLineItem] | None = None,
) -> Quote:
    clause = (
        "Late delivery penalty: 1% of order value per week of delay." if penalty_present else None
    )
    items = [item or make_line_item(line_total=line_total)]
    if extra_items:
        items.extend(extra_items)
    return Quote(
        supplier_name=f(supplier_name),
        quotation_number=f(quotation_number),
        quote_date=f("2026-10-21"),
        purchase_request_reference=f("PR-0000-001"),
        line_items=items,
        subtotal=f(subtotal),
        vat_statement=f(vat_statement, snippet="VAT 15%"),
        vat_rate=f(vat_rate),
        vat_amount=f(vat_amount),
        total=f(total),
        tin=f(tin),
        bin=f(bin_value),
        terms=Terms(
            advance_percent=f(advance),
            payment_days=f(payment_days),
            delivery_days=f(delivery_days),
            late_penalty_clause=f(clause, snippet=clause or "clause"),
            penalty_percent_per_week=f(penalty),
            penalty_basis_order_value=f(penalty_basis),
            validity_days=f(validity_days),
        ),
    )


def make_pr_line(
    *,
    item_code: str = "A",
    description: str = "Item A",
    quantity: Decimal = Decimal("100"),
    max_price: Decimal = Decimal("10"),
    pr_number: str = "PR-0000-001",
) -> PurchaseRequestLine:
    return PurchaseRequestLine(
        pr_number=pr_number,
        item_code=item_code,
        description=description,
        unit="piece",
        quantity_requested=quantity,
        max_unit_price=max_price,
        csv_line=f"{pr_number},{item_code},{description},piece,{quantity},{max_price}",
    )


def make_pr(*lines: PurchaseRequestLine) -> PurchaseRequest:
    request_lines = list(lines) or [make_pr_line()]
    return PurchaseRequest(pr_number=request_lines[0].pr_number, lines=request_lines)


def compare(quote: Quote, pr: PurchaseRequest | None = None) -> PurchaseRequestComparison:
    return match_purchase_request_line(quote.line_items[0], pr or make_pr())


def by_code(checks: list[Any], code: str) -> Any:
    matches = [check for check in checks if check.code == code]
    assert len(matches) == 1, f"expected exactly one check with code {code}"
    return matches[0]
