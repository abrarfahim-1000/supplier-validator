"""Collect fields a rule depends on that are not usable, for the result payload."""

from __future__ import annotations

from typing import Any

from checker.schemas import ExtractedField, FieldFlag, FieldStatus, Quote


def _flag(name: str, field: ExtractedField[Any]) -> FieldFlag | None:
    if field.status is FieldStatus.OK:
        return None
    return FieldFlag(
        code=f"FIELD-{field.status.value.upper()}",
        field=name,
        detail=field.note or field.status.value,
    )


def collect_flags(quote: Quote) -> list[FieldFlag]:
    fields: list[tuple[str, ExtractedField[Any]]] = [
        ("tin", quote.tin),
        ("bin", quote.bin),
        ("vat_rate", quote.vat_rate),
        ("vat_amount", quote.vat_amount),
        ("subtotal", quote.subtotal),
        ("total", quote.total),
        ("advance_percent", quote.terms.advance_percent),
        ("payment_days", quote.terms.payment_days),
        ("delivery_days", quote.terms.delivery_days),
        ("late_penalty_clause", quote.terms.late_penalty_clause),
        ("penalty_percent_per_week", quote.terms.penalty_percent_per_week),
        ("penalty_basis_order_value", quote.terms.penalty_basis_order_value),
        ("validity_days", quote.terms.validity_days),
    ]
    for index, item in enumerate(quote.line_items, start=1):
        fields.extend(
            [
                (f"line_items[{index}].quantity", item.quantity),
                (f"line_items[{index}].unit_price", item.unit_price),
                (f"line_items[{index}].line_total", item.line_total),
            ]
        )
    flags = [_flag(name, field) for name, field in fields]
    return [flag for flag in flags if flag is not None]
