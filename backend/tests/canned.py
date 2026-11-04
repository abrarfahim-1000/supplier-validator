"""Canned extraction output for the synthetic test PDF. Written for this repo only."""

from __future__ import annotations

from typing import Any

SYNTHETIC_LINES = [
    "Synthetic Fabrics Ltd",
    "QUOTATION",
    "Quotation no. QT-TEST-001",
    "Date 2026-11-01",
    "Reference PR-0000-001",
    "Item A",
    "Blue denim roll, 12 oz",
    "100",
    "piece",
    "10.00",
    "1,000.00",
    "Subtotal 1,000.00",
    "VAT 15% 150.00",
    "Total 1,150.00",
    "Supplier TIN: 000000000000 BIN: 000000000-0000",
    "1. Payment. 10% advance payable with the purchase order. Balance within 45 days"
    " after delivery.",
    "2. Delivery. Delivery within 25 days of PO.",
    "3. Delay. Late delivery penalty: 1% of order value per week of delay.",
    "4. Validity. This quotation is valid for 45 days from the date above.",
]


def rv(value: str, source: str) -> dict[str, str]:
    return {"value": value, "source": source}


def line_item() -> dict[str, Any]:
    return {
        "item_code": rv("A", "Item A"),
        "description": rv("Blue denim roll, 12 oz", "Blue denim roll, 12 oz"),
        "unit": rv("piece", "piece"),
        "quantity": rv("100", "100"),
        "unit_price": rv("10.00", "10.00"),
        "line_total": rv("1,000.00", "1,000.00"),
    }


def extraction_payload(*, line_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    tin_source = "Supplier TIN: 000000000000 BIN: 000000000-0000"
    return {
        "supplier_name": rv("Synthetic Fabrics Ltd", "Synthetic Fabrics Ltd"),
        "quotation_number": rv("QT-TEST-001", "Quotation no. QT-TEST-001"),
        "quote_date": rv("2026-11-01", "Date 2026-11-01"),
        "purchase_request_reference": rv("PR-0000-001", "Reference PR-0000-001"),
        "line_items": line_items if line_items is not None else [line_item()],
        "subtotal": rv("1,000.00", "Subtotal 1,000.00"),
        "vat_statement": rv("VAT 15%", "VAT 15% 150.00"),
        "vat_rate": rv("15%", "VAT 15% 150.00"),
        "vat_amount": rv("150.00", "VAT 15% 150.00"),
        "total": rv("1,150.00", "Total 1,150.00"),
        "tin": rv("000000000000", tin_source),
        "bin": rv("000000000-0000", tin_source),
        "terms": {
            "advance_payment": rv("10%", "10% advance payable with the purchase order."),
            "payment_days": rv("45 days", "Balance within 45 days after delivery."),
            "delivery_days": rv("25 days", "Delivery within 25 days of PO."),
            "late_delivery_penalty": rv(
                "1% of order value per week",
                "Late delivery penalty: 1% of order value per week of delay.",
            ),
            "validity_days": rv(
                "45 days", "This quotation is valid for 45 days from the date above."
            ),
        },
    }
