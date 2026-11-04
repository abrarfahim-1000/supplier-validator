from __future__ import annotations

from decimal import Decimal

from builders import by_code, compare, make_line_item, make_pr, make_pr_line, make_quote
from checker.checks import run_all_checks
from checker.schemas import CheckStatus, FieldStatus, QuoteLineItem


def checks_for(quote, rules, pr=None):
    return run_all_checks(quote, compare(quote, pr), rules)


def test_price_below_maximum_passes(rules) -> None:
    quote = make_quote(item=make_line_item(unit_price=Decimal("480")))
    pr = make_pr(make_pr_line(max_price=Decimal("480")))
    checks = checks_for(quote, rules, pr)
    assert by_code(checks, "REJ-01").status is CheckStatus.PASS
    assert by_code(checks, "NP-01").status is CheckStatus.PASS


def test_exactly_three_percent_over_is_needs_person_not_reject(rules) -> None:
    quote = make_quote(item=make_line_item(unit_price=Decimal("103")))
    pr = make_pr(make_pr_line(max_price=Decimal("100")))
    checks = checks_for(quote, rules, pr)
    assert by_code(checks, "REJ-01").status is CheckStatus.PASS
    assert by_code(checks, "NP-01").status is CheckStatus.NEEDS_PERSON


def test_more_than_three_percent_over_rejects(rules) -> None:
    quote = make_quote(item=make_line_item(unit_price=Decimal("103.01")))
    pr = make_pr(make_pr_line(max_price=Decimal("100")))
    checks = checks_for(quote, rules, pr)
    assert by_code(checks, "REJ-01").status is CheckStatus.REJECT
    assert by_code(checks, "NP-01").status is CheckStatus.PASS


def test_unreadable_price_is_needs_person(rules) -> None:
    item = QuoteLineItem(
        item_code=make_line_item().item_code,
        description=make_line_item().description,
        unit=make_line_item().unit,
        quantity=make_line_item().quantity,
        unit_price=make_line_item().unit_price.model_copy(
            update={"value": None, "status": FieldStatus.AMBIGUOUS, "note": "unreadable"}
        ),
        line_total=make_line_item().line_total,
    )
    quote = make_quote(item=item)
    checks = checks_for(quote, rules)
    assert by_code(checks, "REJ-01").status is CheckStatus.NEEDS_PERSON
    assert by_code(checks, "NP-01").status is CheckStatus.NEEDS_PERSON


def test_unmatched_quote_is_needs_person_for_price_rules(rules) -> None:
    quote = make_quote(item=make_line_item(item_code="Z", description="Unlisted item"))
    checks = checks_for(quote, rules)
    assert by_code(checks, "REJ-01").status is CheckStatus.NEEDS_PERSON
    assert by_code(checks, "NP-01").status is CheckStatus.NEEDS_PERSON
    assert by_code(checks, "EDGE-PURCHASE-REQUEST-MATCH").status is CheckStatus.NEEDS_PERSON


def test_price_threshold_is_read_from_the_rules_file(rules) -> None:
    loose = rules.model_copy(
        update={
            "thresholds": rules.thresholds.model_copy(
                update={"price_over_max_percent": Decimal("50")}
            )
        }
    )
    quote = make_quote(item=make_line_item(unit_price=Decimal("110"), line_total=Decimal("11000")))
    pr = make_pr(make_pr_line(max_price=Decimal("100")))
    checks = checks_for(quote, loose, pr)
    assert by_code(checks, "REJ-01").status is CheckStatus.PASS
    assert by_code(checks, "NP-01").status is CheckStatus.NEEDS_PERSON
