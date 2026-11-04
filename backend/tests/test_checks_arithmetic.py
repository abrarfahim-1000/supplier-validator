from __future__ import annotations

from decimal import Decimal

from builders import by_code, compare, f, make_quote
from checker.checks import run_all_checks
from checker.schemas import CheckStatus, FieldStatus


def checks_for(quote, rules):
    return run_all_checks(quote, compare(quote), rules)


def test_consistent_numbers_pass(rules) -> None:
    assert by_code(checks_for(make_quote(), rules), "NP-06").status is CheckStatus.PASS


def test_wrong_line_total_is_needs_person(rules) -> None:
    checks = checks_for(
        make_quote(total=Decimal("1151"), subtotal=Decimal("1001"), line_total=Decimal("1001")),
        rules,
    )
    assert by_code(checks, "NP-06").status is CheckStatus.NEEDS_PERSON


def test_wrong_subtotal_is_needs_person(rules) -> None:
    checks = checks_for(make_quote(subtotal=Decimal("999")), rules)
    assert by_code(checks, "NP-06").status is CheckStatus.NEEDS_PERSON


def test_wrong_total_is_needs_person(rules) -> None:
    checks = checks_for(make_quote(total=Decimal("1160")), rules)
    assert by_code(checks, "NP-06").status is CheckStatus.NEEDS_PERSON


def test_tax_inclusive_total_is_verified_against_the_line(rules) -> None:
    quote = make_quote(
        subtotal=None,
        vat_statement="Total (all taxes included)",
        vat_rate=None,
        vat_amount=None,
        total=Decimal("1000"),
    )
    assert by_code(checks_for(quote, rules), "NP-06").status is CheckStatus.PASS


def test_vat_without_subtotal_is_needs_person(rules) -> None:
    quote = make_quote(subtotal=None, vat_amount=Decimal("150"), total=Decimal("1150"))
    assert by_code(checks_for(quote, rules), "NP-06").status is CheckStatus.NEEDS_PERSON


def test_an_unreadable_vat_amount_is_not_reported_as_a_bad_sum(rules) -> None:
    quote = make_quote(subtotal=Decimal("720000"), total=Decimal("828000"))
    line = quote.line_items[0].model_copy(
        update={
            "quantity": f(Decimal("20000")),
            "unit_price": f(Decimal("36")),
            "line_total": f(Decimal("720000")),
        }
    )
    quote = quote.model_copy(
        update={
            "line_items": [line],
            "vat_amount": f(Decimal("108000"), status=FieldStatus.UNVERIFIED),
        }
    )

    result = by_code(checks_for(quote, rules), "NP-06")

    assert result.status is CheckStatus.NEEDS_PERSON
    assert "could not be verified" in result.detail
    assert "does not equal" not in result.detail


def test_no_verifiable_numbers_is_needs_person(rules) -> None:
    quote = make_quote(subtotal=None, vat_amount=None, total=None)
    broken_line = quote.line_items[0].model_copy(update={"line_total": f(None)})
    quote = quote.model_copy(update={"line_items": [broken_line]})
    assert by_code(checks_for(quote, rules), "NP-06").status is CheckStatus.NEEDS_PERSON
