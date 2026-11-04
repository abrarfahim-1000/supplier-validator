"""One deterministic function per company rule, plus the few edge cases that have no rule ID.

Every function is pure: it reads the normalized quote, the purchase request comparison and
the loaded rules, and returns a :class:`CheckResult`. Nothing short-circuits; the caller
runs every check and the decision module applies precedence. Thresholds come only from the
rules file.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from checker.rules import Rule, RuleSet
from checker.schemas import (
    CheckResult,
    CheckStatus,
    ComparisonIssue,
    Evidence,
    EvidenceSource,
    ExtractedField,
    FieldStatus,
    LineComparison,
    PurchaseRequestComparison,
    Quote,
    QuoteLineItem,
)

_CENT = Decimal("0.01")
_TENTH = Decimal("0.1")
_BASIS_POINT = Decimal(100)

EDGE_MULTIPLE_LINE_ITEMS = "EDGE-MULTIPLE-LINE-ITEMS"
EDGE_PENALTY = "EDGE-PENALTY"
EDGE_PURCHASE_REQUEST_MATCH = "EDGE-PURCHASE-REQUEST-MATCH"


def fmt_money(value: Decimal) -> str:
    return f"BDT {value.quantize(_CENT):,f}"


def fmt_percent(value: Decimal) -> str:
    return f"{value.quantize(_TENTH)}%"


@dataclass(frozen=True)
class CheckContext:
    quote: Quote
    comparison: PurchaseRequestComparison
    rules: RuleSet


def _rule(ctx: CheckContext, rule_id: str) -> Rule:
    return ctx.rules.rule(rule_id)


def _result(
    rule: Rule,
    status: CheckStatus,
    detail: str,
    evidence: list[Evidence] | None = None,
) -> CheckResult:
    return CheckResult(
        code=rule.id,
        rule_id=rule.id,
        title=rule.title,
        status=status,
        detail=detail,
        evidence=evidence or [],
    )


def _edge(
    code: str,
    title: str,
    status: CheckStatus,
    detail: str,
    evidence: list[Evidence] | None = None,
) -> CheckResult:
    return CheckResult(
        code=code,
        rule_id=None,
        title=title,
        status=status,
        detail=detail,
        evidence=evidence or [],
    )


def _evidence(field: ExtractedField[Any], name: str) -> list[Evidence]:
    if not field.snippet:
        return []
    return [Evidence(source=EvidenceSource.SUPPLIER_DOCUMENT, snippet=field.snippet, field=name)]


def _comparison_evidence(compared: LineComparison) -> Evidence:
    return Evidence(
        source=EvidenceSource.PURCHASE_REQUEST,
        snippet=compared.request_line_text,
        field="purchase_request_line",
    )


def _field_problem(field: ExtractedField[Any], name: str) -> str:
    reason = field.note or field.status.value
    return f"{name} cannot be used ({reason})"


def _only_line(quote: Quote) -> QuoteLineItem | None:
    if len(quote.line_items) != 1:
        return None
    return quote.line_items[0]


def _line_problem(quote: Quote) -> str:
    return (
        "the quote must contain exactly one line item to compare it with the purchase request"
        f" (found {len(quote.line_items)})"
    )


def _pending_price_detail(ctx: CheckContext) -> str | None:
    """Why a price or quantity rule cannot be evaluated, or None when it can."""
    if _only_line(ctx.quote) is None:
        return _line_problem(ctx.quote)
    if ctx.comparison.issue is not ComparisonIssue.NONE:
        return ctx.comparison.detail or ctx.comparison.issue.value
    if ctx.comparison.line is None:
        return "the quote has no purchase request comparison"
    return None


# --- Reject rules -----------------------------------------------------------------------


def check_rej_01_price_over_max(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "REJ-01")
    threshold = ctx.rules.thresholds.price_over_max_percent
    pending = _pending_price_detail(ctx)
    if pending:
        return _result(rule, CheckStatus.NEEDS_PERSON, f"price not checked: {pending}")
    assert ctx.comparison.line is not None
    line = _only_line(ctx.quote)
    assert line is not None
    if not line.unit_price.usable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            _field_problem(line.unit_price, "quoted unit price"),
        )
    compared = ctx.comparison.line
    percent = compared.unit_price_difference_percent
    evidence = [*_evidence(line.unit_price, "unit_price"), _comparison_evidence(compared)]
    if percent > threshold:
        return _result(
            rule,
            CheckStatus.REJECT,
            f"quoted unit price {fmt_money(compared.quoted_unit_price)} is {fmt_percent(percent)}"
            f" above the maximum {fmt_money(compared.max_unit_price)}, more than {threshold}%",
            evidence,
        )
    return _result(
        rule,
        CheckStatus.PASS,
        f"quoted unit price {fmt_money(compared.quoted_unit_price)} is {fmt_percent(percent)}"
        f" against the maximum {fmt_money(compared.max_unit_price)}",
        evidence,
    )


def check_rej_02_advance(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "REJ-02")
    threshold = ctx.rules.thresholds.advance_max_percent
    advance = ctx.quote.terms.advance_percent
    if not advance.usable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            _field_problem(advance, "advance payment"),
            _evidence(advance, "advance_payment"),
        )
    evidence = _evidence(advance, "advance_payment")
    assert advance.value is not None
    if advance.value > threshold:
        return _result(
            rule,
            CheckStatus.REJECT,
            f"advance payment is {fmt_percent(advance.value)}, more than {threshold}%",
            evidence,
        )
    return _result(
        rule,
        CheckStatus.PASS,
        f"advance payment is {fmt_percent(advance.value)}, within {threshold}%",
        evidence,
    )


def check_rej_03_penalty_clause(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "REJ-03")
    clause = ctx.quote.terms.late_penalty_clause
    if clause.status is FieldStatus.MISSING:
        return _result(
            rule,
            CheckStatus.REJECT,
            "the contract has no late-delivery penalty clause",
        )
    if clause.status is not FieldStatus.OK:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            _field_problem(clause, "late-delivery penalty clause"),
            _evidence(clause, "late_delivery_penalty"),
        )
    return _result(
        rule,
        CheckStatus.PASS,
        "the contract states a late-delivery penalty",
        _evidence(clause, "late_delivery_penalty"),
    )


def check_rej_04_tin_bin(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "REJ-04")
    tin = ctx.quote.tin
    bin_ = ctx.quote.bin
    missing = [
        name for name, field in (("TIN", tin), ("BIN", bin_)) if field.status is FieldStatus.MISSING
    ]
    unusable = [
        name
        for name, field in (("TIN", tin), ("BIN", bin_))
        if field.status in (FieldStatus.AMBIGUOUS, FieldStatus.UNVERIFIED)
    ]
    evidence = _evidence(tin, "tin") + _evidence(bin_, "bin")
    if missing:
        return _result(
            rule,
            CheckStatus.REJECT,
            f"supplier {' and '.join(missing)} is missing",
            evidence,
        )
    if unusable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            f"supplier {' and '.join(unusable)} could not be read reliably",
            evidence,
        )
    return _result(rule, CheckStatus.PASS, "supplier TIN and BIN are present", evidence)


def check_rej_05_delivery(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "REJ-05")
    threshold = ctx.rules.thresholds.delivery_reject_days
    delivery = ctx.quote.terms.delivery_days
    if not delivery.usable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            _field_problem(delivery, "delivery timeframe"),
            _evidence(delivery, "delivery_days"),
        )
    assert delivery.value is not None
    evidence = _evidence(delivery, "delivery_days")
    if delivery.value > threshold:
        return _result(
            rule,
            CheckStatus.REJECT,
            f"delivery is promised in {delivery.value} days, later than {threshold} days",
            evidence,
        )
    return _result(
        rule,
        CheckStatus.PASS,
        f"delivery is promised in {delivery.value} days, not later than {threshold} days",
        evidence,
    )


# --- Needs-person rules -----------------------------------------------------------------


def check_np_01_price_within_band(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "NP-01")
    threshold = ctx.rules.thresholds.price_over_max_percent
    pending = _pending_price_detail(ctx)
    if pending:
        return _result(rule, CheckStatus.NEEDS_PERSON, f"price not checked: {pending}")
    assert ctx.comparison.line is not None
    line = _only_line(ctx.quote)
    assert line is not None
    if not line.unit_price.usable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            _field_problem(line.unit_price, "quoted unit price"),
        )
    compared = ctx.comparison.line
    percent = compared.unit_price_difference_percent
    evidence = [*_evidence(line.unit_price, "unit_price"), _comparison_evidence(compared)]
    if Decimal(0) < percent <= threshold:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            f"quoted unit price {fmt_money(compared.quoted_unit_price)} is {fmt_percent(percent)}"
            f" above the maximum {fmt_money(compared.max_unit_price)}, within the {threshold}%"
            " review band; a person must confirm",
            evidence,
        )
    return _result(
        rule,
        CheckStatus.PASS,
        f"quoted unit price is not in the review band above the maximum ({fmt_percent(percent)})",
        evidence,
    )


def check_np_02_quantity(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "NP-02")
    threshold = ctx.rules.thresholds.quantity_gap_percent
    pending = _pending_price_detail(ctx)
    if pending:
        return _result(rule, CheckStatus.NEEDS_PERSON, f"quantity not checked: {pending}")
    assert ctx.comparison.line is not None
    line = _only_line(ctx.quote)
    assert line is not None
    if not line.quantity.usable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            _field_problem(line.quantity, "quoted quantity"),
        )
    compared = ctx.comparison.line
    gap = abs(compared.quantity_difference) / compared.requested_quantity * _BASIS_POINT
    evidence = [*_evidence(line.quantity, "quantity"), _comparison_evidence(compared)]
    if gap > threshold:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            f"quoted quantity {compared.quoted_quantity} differs from the requested"
            f" {compared.requested_quantity} by {fmt_percent(gap)}, more than {threshold}%",
            evidence,
        )
    return _result(
        rule,
        CheckStatus.PASS,
        f"quoted quantity differs from the request by {fmt_percent(gap)}",
        evidence,
    )


def check_np_03_payment_terms(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "NP-03")
    minimum = ctx.rules.thresholds.payment_min_days
    maximum = ctx.rules.thresholds.payment_max_days
    payment = ctx.quote.terms.payment_days
    if not payment.usable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            _field_problem(payment, "payment terms"),
            _evidence(payment, "payment_days"),
        )
    assert payment.value is not None
    evidence = _evidence(payment, "payment_days")
    if payment.value < minimum or payment.value > maximum:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            f"payment is due {payment.value} days after delivery, outside {minimum} to"
            f" {maximum} days",
            evidence,
        )
    return _result(
        rule,
        CheckStatus.PASS,
        f"payment is due {payment.value} days after delivery, within {minimum} to {maximum} days",
        evidence,
    )


def check_np_04_delivery_review_band(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "NP-04")
    minimum = ctx.rules.thresholds.delivery_review_min_days
    maximum = ctx.rules.thresholds.delivery_review_max_days
    delivery = ctx.quote.terms.delivery_days
    if not delivery.usable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            _field_problem(delivery, "delivery timeframe"),
            _evidence(delivery, "delivery_days"),
        )
    assert delivery.value is not None
    evidence = _evidence(delivery, "delivery_days")
    if minimum <= delivery.value <= maximum:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            f"delivery is promised in {delivery.value} days, inside the {minimum} to {maximum}"
            " day review band",
            evidence,
        )
    return _result(
        rule,
        CheckStatus.PASS,
        f"delivery is promised in {delivery.value} days, outside the {minimum} to {maximum}"
        " day review band",
        evidence,
    )


def check_np_05_vat(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "NP-05")
    expected = ctx.rules.thresholds.vat_percent
    rate = ctx.quote.vat_rate
    amount = ctx.quote.vat_amount
    statement = ctx.quote.vat_statement
    evidence = (
        _evidence(statement, "vat_statement")
        + _evidence(rate, "vat_rate")
        + _evidence(amount, "vat_amount")
    )
    if rate.usable and amount.usable and rate.value == expected:
        return _result(
            rule,
            CheckStatus.PASS,
            f"VAT is shown separately at {expected}% with an amount",
            evidence,
        )
    problems: list[str] = []
    if rate.status is FieldStatus.MISSING:
        problems.append("no VAT rate is stated")
    elif not rate.usable:
        problems.append(_field_problem(rate, "VAT rate"))
    elif rate.value != expected:
        problems.append(f"VAT is stated at {rate.value}%, not {expected}%")
    if amount.status is FieldStatus.MISSING:
        problems.append("no VAT amount is stated")
    elif not amount.usable:
        problems.append(_field_problem(amount, "VAT amount"))
    return _result(
        rule,
        CheckStatus.NEEDS_PERSON,
        f"VAT is not shown separately at {expected}%: " + "; ".join(problems),
        evidence,
    )


def check_np_06_arithmetic(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "NP-06")
    tolerance = ctx.rules.thresholds.arithmetic_tolerance_bdt
    line = _only_line(ctx.quote)
    if line is None:
        return _result(rule, CheckStatus.NEEDS_PERSON, _line_problem(ctx.quote))
    problems: list[str] = []
    verified = 0
    evidence: list[Evidence] = []

    quantity = line.quantity
    price = line.unit_price
    line_total = line.line_total
    subtotal = ctx.quote.subtotal
    vat_amount = ctx.quote.vat_amount
    total = ctx.quote.total
    evidence += (
        _evidence(quantity, "quantity")
        + _evidence(price, "unit_price")
        + _evidence(line_total, "line_total")
        + _evidence(subtotal, "subtotal")
        + _evidence(vat_amount, "vat_amount")
        + _evidence(total, "total")
    )

    if quantity.usable and price.usable and line_total.usable:
        assert (
            quantity.value is not None and price.value is not None and line_total.value is not None
        )
        verified += 1
        expected_total = quantity.value * price.value
        if abs(expected_total - line_total.value) > tolerance:
            problems.append(
                f"line total {fmt_money(line_total.value)} does not equal quantity x unit price"
                f" ({fmt_money(expected_total)})"
            )

    if subtotal.usable and line_total.usable:
        assert subtotal.value is not None and line_total.value is not None
        verified += 1
        if abs(subtotal.value - line_total.value) > tolerance:
            problems.append(
                f"subtotal {fmt_money(subtotal.value)} does not equal the line total"
                f" {fmt_money(line_total.value)}"
            )

    if vat_amount.usable and subtotal.usable and total.usable:
        assert (
            vat_amount.value is not None and subtotal.value is not None and total.value is not None
        )
        verified += 1
        expected_total = subtotal.value + vat_amount.value
        if abs(expected_total - total.value) > tolerance:
            problems.append(
                f"total {fmt_money(total.value)} does not equal subtotal plus VAT"
                f" ({fmt_money(expected_total)})"
            )
    elif vat_amount.usable and not subtotal.usable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            "VAT is stated without a subtotal, so the total cannot be verified",
            evidence,
        )
    elif total.usable and subtotal.usable:
        zero_rated = ctx.quote.vat_rate.usable and ctx.quote.vat_rate.value == 0
        if vat_amount.status is not FieldStatus.MISSING and not zero_rated:
            # VAT is stated but its amount could not be read: the gap between subtotal and
            # total is not evidence of a bad sum, so do not report one.
            return _result(
                rule,
                CheckStatus.NEEDS_PERSON,
                "VAT is stated but its amount could not be verified,"
                " so the total cannot be checked",
                evidence,
            )
        assert total.value is not None and subtotal.value is not None
        verified += 1
        if abs(total.value - subtotal.value) > tolerance:
            problems.append(
                f"total {fmt_money(total.value)} does not equal the stated subtotal"
                f" {fmt_money(subtotal.value)} with no separate VAT"
            )
    elif total.usable and line_total.usable:
        assert total.value is not None and line_total.value is not None
        verified += 1
        if abs(total.value - line_total.value) > tolerance:
            problems.append(
                f"total {fmt_money(total.value)} does not equal the line total"
                f" {fmt_money(line_total.value)}"
            )

    if problems:
        return _result(rule, CheckStatus.NEEDS_PERSON, "; ".join(problems), evidence)
    if verified == 0:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            "no totals could be verified against the quoted numbers",
            evidence,
        )
    return _result(
        rule,
        CheckStatus.PASS,
        f"the quoted numbers add up ({verified} relationship(s) checked)",
        evidence,
    )


def check_np_07_validity(ctx: CheckContext) -> CheckResult:
    rule = _rule(ctx, "NP-07")
    minimum = ctx.rules.thresholds.validity_min_days
    validity = ctx.quote.terms.validity_days
    if not validity.usable:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            _field_problem(validity, "quotation validity"),
            _evidence(validity, "validity_days"),
        )
    assert validity.value is not None
    evidence = _evidence(validity, "validity_days")
    if validity.value < minimum:
        return _result(
            rule,
            CheckStatus.NEEDS_PERSON,
            f"the quotation is valid for {validity.value} days, less than {minimum} days",
            evidence,
        )
    return _result(
        rule,
        CheckStatus.PASS,
        f"the quotation is valid for {validity.value} days, not less than {minimum} days",
        evidence,
    )


# --- Edge cases without a rule ID -------------------------------------------------------


def check_edge_line_items(ctx: CheckContext) -> CheckResult:
    count = len(ctx.quote.line_items)
    if count == 1:
        return _edge(
            EDGE_MULTIPLE_LINE_ITEMS,
            "Single line item",
            CheckStatus.PASS,
            "the quote has one line item",
        )
    return _edge(
        EDGE_MULTIPLE_LINE_ITEMS,
        "Single line item",
        CheckStatus.NEEDS_PERSON,
        _line_problem(ctx.quote),
    )


def check_edge_penalty_minimum(ctx: CheckContext) -> CheckResult:
    minimum = ctx.rules.thresholds.late_penalty_min_percent_per_week
    title = "Late-delivery penalty minimum"
    clause = ctx.quote.terms.late_penalty_clause
    percent = ctx.quote.terms.penalty_percent_per_week
    basis = ctx.quote.terms.penalty_basis_order_value
    if clause.status is FieldStatus.MISSING:
        return _edge(
            EDGE_PENALTY,
            title,
            CheckStatus.PASS,
            "no penalty clause to assess; the missing clause is handled by REJ-03",
        )
    evidence = _evidence(clause, "late_delivery_penalty")
    if not percent.usable:
        return _edge(
            EDGE_PENALTY,
            title,
            CheckStatus.NEEDS_PERSON,
            _field_problem(percent, "penalty rate"),
            evidence,
        )
    assert percent.value is not None
    if percent.value < minimum:
        return _edge(
            EDGE_PENALTY,
            title,
            CheckStatus.NEEDS_PERSON,
            f"penalty is {fmt_percent(percent.value)} per week, below the {minimum}% minimum",
            evidence,
        )
    if not basis.usable:
        return _edge(
            EDGE_PENALTY,
            title,
            CheckStatus.NEEDS_PERSON,
            "the penalty basis (a percentage of order value) could not be verified",
            evidence,
        )
    if basis.value is False:
        return _edge(
            EDGE_PENALTY,
            title,
            CheckStatus.NEEDS_PERSON,
            "penalty is not stated as a percentage of order value, so the minimum cannot be"
            " confirmed",
            evidence,
        )
    return _edge(
        EDGE_PENALTY,
        title,
        CheckStatus.PASS,
        f"penalty is {fmt_percent(percent.value)} of order value per week, at or above the"
        f" {minimum}% minimum",
        evidence,
    )


def check_edge_purchase_request_match(ctx: CheckContext) -> CheckResult:
    title = "Purchase request match"
    comparison = ctx.comparison
    if comparison.issue is ComparisonIssue.NONE:
        assert comparison.line is not None
        return _edge(
            title=title,
            code=EDGE_PURCHASE_REQUEST_MATCH,
            status=CheckStatus.PASS,
            detail=f"matched purchase request item {comparison.line.item_code} by"
            f" {comparison.line.matched_by.value}",
            evidence=[_comparison_evidence(comparison.line)],
        )
    return _edge(
        EDGE_PURCHASE_REQUEST_MATCH,
        title,
        CheckStatus.NEEDS_PERSON,
        comparison.detail or comparison.issue.value,
    )


def run_all_checks(
    quote: Quote,
    comparison: PurchaseRequestComparison,
    rules: RuleSet,
) -> list[CheckResult]:
    ctx = CheckContext(quote=quote, comparison=comparison, rules=rules)
    return [
        check_rej_01_price_over_max(ctx),
        check_rej_02_advance(ctx),
        check_rej_03_penalty_clause(ctx),
        check_rej_04_tin_bin(ctx),
        check_rej_05_delivery(ctx),
        check_np_01_price_within_band(ctx),
        check_np_02_quantity(ctx),
        check_np_03_payment_terms(ctx),
        check_np_04_delivery_review_band(ctx),
        check_np_05_vat(ctx),
        check_np_06_arithmetic(ctx),
        check_np_07_validity(ctx),
        check_edge_line_items(ctx),
        check_edge_penalty_minimum(ctx),
        check_edge_purchase_request_match(ctx),
    ]
