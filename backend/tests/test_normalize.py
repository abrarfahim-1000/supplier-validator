from __future__ import annotations

from decimal import Decimal

import pytest

from checker.normalize import (
    build_field,
    normalize_quote,
    parse_advance_percent,
    parse_days,
    parse_money,
    parse_percent,
    parse_text,
    snippet_in_source,
)
from checker.schemas import FieldStatus, RawLineItem, RawQuote, RawTerms, RawValue


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Delivery within 24 days of receiving the purchase order.", 24),
        ("Delivery within 4 weeks of PO.", 28),
        ("This quotation is valid for 30 days from the date above.", 30),
        ("within 45 days after delivery", 45),
    ],
)
def test_days_are_parsed_including_weeks(text: str, expected: int) -> None:
    parsed = parse_days(text)
    assert parsed.value == Decimal(expected)


@pytest.mark.parametrize(
    "text",
    [
        "Payment within 30 to 90 days as agreed by both parties.",
        "Delivery within 30-60 days",
        "This quotation is valid for less than 30 days",
        "Delivery as agreed",
        "Delivery on a date to be confirmed",
    ],
)
def test_ambiguous_timeframes_stay_flagged(text: str) -> None:
    parsed = parse_days(text)
    assert parsed.value is None
    assert parsed.note


def test_money_strips_commas() -> None:
    assert parse_money("1,234,567.89").value == Decimal("1234567.89")
    assert parse_money("BDT 12.50").value == Decimal("12.50")


def test_percent_needs_one_value() -> None:
    assert parse_percent("VAT 15%").value == Decimal("15")
    assert parse_percent("10% now, 20% later").value is None


def test_advance_handles_no_advance_and_duplicates() -> None:
    assert parse_advance_percent("No advance payment required.").value == Decimal(0)
    assert parse_advance_percent("10% advance payable with the purchase order.").value == Decimal(
        10
    )
    duplicate = (
        "40% advance payable with the purchase order. 40% advance with the purchase order,"
        " balance 60% within 30 days of delivery."
    )
    assert parse_advance_percent(duplicate).value == Decimal(40)


def test_advance_conflict_is_ambiguous() -> None:
    parsed = parse_advance_percent("10% advance with the order and advance of 30% on delivery")
    assert parsed.value is None


def test_snippet_must_appear_verbatim_ignoring_wrapping() -> None:
    source = "Balance payable within 45 days after delivery and\nacceptance of goods."
    assert snippet_in_source("Balance payable within 45 days after delivery and acceptance", source)
    assert not snippet_in_source("Balance payable within 30 days", source)


def test_field_is_unverified_when_the_snippet_is_invented() -> None:
    field = build_field(
        RawValue(value="20 days", source="Delivery within 20 days of PO."),
        parse_days,
        "Delivery within 25 days of PO.",
    )
    assert field.status is FieldStatus.UNVERIFIED


def test_a_rebuilt_quote_is_replaced_by_the_document_line() -> None:
    source = "Supplier TIN: 000000000001 BIN: 000000001-0001\nTotal 14,176.81"
    field = build_field(
        RawValue(value="000000001-0001", source="Supplier BIN: 000000001-0001"),
        parse_text,
        source,
    )

    assert field.status is FieldStatus.OK
    assert field.value == "000000001-0001"
    assert field.snippet == "Supplier TIN: 000000000001 BIN: 000000001-0001"


def test_a_value_printed_on_several_lines_is_not_located() -> None:
    source = "VAT 15% 100.00\nEarly payment discount 15% offered"
    field = build_field(
        RawValue(value="15%", source="a rate of 15% applies"),
        parse_percent,
        source,
    )

    assert field.status is FieldStatus.UNVERIFIED


def test_a_rebuilt_quote_for_a_value_absent_from_the_document_stays_unverified() -> None:
    field = build_field(
        RawValue(value="999.00", source="VAT 999.00"),
        parse_money,
        "VAT 15% 1,234.56",
    )

    assert field.status is FieldStatus.UNVERIFIED


def test_normalize_quote_end_to_end() -> None:
    source = (
        "Synthetic Widget, 10 cm 1,234 piece 9.99 12,327.66\n"
        "Supplier TIN: 000000000001 BIN: 000000001-0001\n"
        "10% advance payable with the purchase order. Balance payable within 45 days after"
        " delivery.\nDelivery within 24 days of receiving the purchase order.\n"
        "Late delivery penalty: 1% of order value for each full week of delay.\n"
        "This quotation is valid for 45 days from the date above.\n"
        "VAT 15% 1,849.15"
    )
    raw = RawQuote(
        line_items=[
            RawLineItem(
                item_code=RawValue(value="S", source="S"),
                quantity=RawValue(value="1,234", source="1,234"),
                unit_price=RawValue(value="9.99", source="9.99"),
            )
        ],
        vat_statement=RawValue(value="VAT 15%", source="VAT 15%"),
        vat_rate=RawValue(value="15%", source="VAT 15%"),
        vat_amount=RawValue(value="1,849.15", source="VAT 15% 1,849.15"),
        tin=RawValue(value="000000000001", source="Supplier TIN: 000000000001 BIN: 000000001-0001"),
        bin=RawValue(
            value="000000001-0001", source="Supplier TIN: 000000000001 BIN: 000000001-0001"
        ),
        terms=RawTerms(
            advance_payment=RawValue(
                value="10%", source="10% advance payable with the purchase order."
            ),
            payment_days=RawValue(
                value="45 days", source="Balance payable within 45 days after delivery."
            ),
            delivery_days=RawValue(
                value="24 days", source="Delivery within 24 days of receiving the purchase order."
            ),
            late_delivery_penalty=RawValue(
                value="1% of order value per week",
                source="Late delivery penalty: 1% of order value for each full week of delay.",
            ),
            validity_days=RawValue(
                value="45 days", source="This quotation is valid for 45 days from the date above."
            ),
        ),
    )

    quote = normalize_quote(raw, source)

    assert quote.line_items[0].quantity.value == Decimal("1234")
    assert quote.line_items[0].unit_price.value == Decimal("9.99")
    assert quote.vat_rate.value == Decimal("15")
    assert quote.terms.advance_percent.value == Decimal("10")
    assert quote.terms.payment_days.value == Decimal("45")
    assert quote.terms.delivery_days.value == Decimal("24")
    assert quote.terms.penalty_percent_per_week.value == Decimal("1")
    assert quote.terms.penalty_basis_order_value.value is True
    assert quote.terms.validity_days.value == Decimal("45")
    assert all(field.status is FieldStatus.OK for field in [quote.tin, quote.bin])
