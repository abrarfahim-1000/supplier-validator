from __future__ import annotations

from decimal import Decimal

from builders import compare, make_line_item, make_pr, make_pr_line, make_quote
from checker.checks import run_all_checks
from checker.decide import decide
from checker.schemas import CheckStatus, Decision


def verdict_for(quote, rules, pr=None):
    return decide(run_all_checks(quote, compare(quote, pr), rules))


def test_every_check_always_runs(rules) -> None:
    checks = run_all_checks(make_quote(), compare(make_quote()), rules)
    assert len(checks) == 15
    assert len({check.code for check in checks}) == 15


def test_clean_quote_approves(rules) -> None:
    verdict = verdict_for(make_quote(), rules)
    assert verdict.decision is Decision.APPROVE
    assert verdict.reasons == []


def test_reject_wins_over_needs_person(rules) -> None:
    quote = make_quote(
        item=make_line_item(unit_price=Decimal("110"), line_total=Decimal("11000")),
        advance=Decimal("40"),
        subtotal=Decimal("11000"),
        vat_amount=Decimal("1650"),
        total=Decimal("12650"),
    )
    verdict = verdict_for(quote, rules, make_pr(make_pr_line(max_price=Decimal("100"))))
    assert verdict.decision is Decision.REJECT
    assert {reason.rule_id for reason in verdict.reasons} >= {"REJ-01", "REJ-02"}


def test_needs_person_when_only_review_rules_hit(rules) -> None:
    quote = make_quote(
        item=make_line_item(unit_price=Decimal("103"), line_total=Decimal("10300")),
        subtotal=Decimal("10300"),
        vat_amount=Decimal("1545"),
        total=Decimal("11845"),
    )
    verdict = verdict_for(quote, rules, make_pr(make_pr_line(max_price=Decimal("100"))))
    assert verdict.decision is Decision.NEEDS_PERSON
    assert [reason.rule_id for reason in verdict.reasons] == ["NP-01"]


def test_reject_reasons_are_listed_first(rules) -> None:
    quote = make_quote(advance=Decimal("40"), delivery_days=Decimal("40"))
    verdict = verdict_for(quote, rules)
    statuses = [reason.rule_id for reason in verdict.reasons]
    assert statuses.index("REJ-02") < statuses.index("NP-04")


def test_edge_case_reason_has_no_rule_id(rules) -> None:
    quote = make_quote(item=make_line_item(item_code="Z", description="Unlisted item"))
    verdict = verdict_for(quote, rules)
    assert verdict.decision is Decision.NEEDS_PERSON
    edge_reasons = [reason for reason in verdict.reasons if reason.rule_id is None]
    assert edge_reasons
    assert all(reason.code.startswith("EDGE-") for reason in edge_reasons)


def test_unreadable_field_never_passes(rules) -> None:
    quote = make_quote(advance=None)
    checks = run_all_checks(quote, compare(quote), rules)
    assert next(check for check in checks if check.code == "REJ-02").status is (
        CheckStatus.NEEDS_PERSON
    )
