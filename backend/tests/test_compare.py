from __future__ import annotations

from decimal import Decimal

from builders import compare, make_line_item, make_pr, make_pr_line, make_quote
from checker.schemas import ComparisonIssue, MatchMethod


def test_matches_by_item_code_first() -> None:
    quote = make_quote(item=make_line_item(item_code="B", description="Metal zipper, 18 cm"))
    pr = make_pr(
        make_pr_line(item_code="A", description="Blue denim roll"),
        make_pr_line(item_code="B", description="Metal zipper, 18 cm", max_price=Decimal("38")),
    )
    comparison = compare(quote, pr)
    assert comparison.issue is ComparisonIssue.NONE
    assert comparison.line is not None
    assert comparison.line.matched_by is MatchMethod.ITEM_CODE
    assert comparison.line.max_unit_price == Decimal("38")


def test_falls_back_to_exact_description() -> None:
    quote = make_quote(item=make_line_item(item_code=None, description="Metal zipper, 18 cm"))
    pr = make_pr(make_pr_line(item_code="B", description="Metal zipper, 18 cm"))
    comparison = compare(quote, pr)
    assert comparison.line is not None
    assert comparison.line.matched_by is MatchMethod.DESCRIPTION


def test_description_may_carry_the_item_code_in_front_of_it() -> None:
    quote = make_quote(item=make_line_item(item_code=None, description="A Blue denim roll, 12 oz"))
    pr = make_pr(make_pr_line(item_code="A", description="Blue denim roll, 12 oz"))

    comparison = compare(quote, pr)

    assert comparison.issue is ComparisonIssue.NONE
    assert comparison.line is not None
    assert comparison.line.matched_by is MatchMethod.DESCRIPTION


def test_description_in_the_item_code_field_still_matches() -> None:
    quote = make_quote(item=make_line_item(item_code="Polyester thread", description=None))
    pr = make_pr(make_pr_line(item_code="C", description="Polyester thread"))

    comparison = compare(quote, pr)

    assert comparison.issue is ComparisonIssue.NONE
    assert comparison.line is not None
    assert comparison.line.matched_by is MatchMethod.DESCRIPTION


def test_a_code_prefix_does_not_match_a_different_description() -> None:
    quote = make_quote(item=make_line_item(item_code=None, description="A Metal zipper, 18 cm"))
    pr = make_pr(make_pr_line(item_code="A", description="Blue denim roll"))

    comparison = compare(quote, pr)

    assert comparison.issue is ComparisonIssue.NO_MATCH


def test_code_and_description_pointing_at_different_lines_is_ambiguous() -> None:
    quote = make_quote(item=make_line_item(item_code="A", description="Metal zipper, 18 cm"))
    pr = make_pr(
        make_pr_line(item_code="A", description="Blue denim roll"),
        make_pr_line(item_code="B", description="Metal zipper, 18 cm"),
    )

    comparison = compare(quote, pr)

    assert comparison.issue is ComparisonIssue.AMBIGUOUS_MATCH


def test_no_match_is_reported_never_guessed() -> None:
    quote = make_quote(item=make_line_item(item_code="Z", description="Unlisted item"))
    comparison = compare(quote, make_pr())
    assert comparison.issue is ComparisonIssue.NO_MATCH
    assert comparison.line is None


def test_more_than_one_match_is_ambiguous() -> None:
    quote = make_quote(item=make_line_item(item_code="A"))
    pr = make_pr(make_pr_line(item_code="A"), make_pr_line(item_code="A"))
    comparison = compare(quote, pr)
    assert comparison.issue is ComparisonIssue.AMBIGUOUS_MATCH


def test_differences_are_computed_from_quoted_values() -> None:
    quote = make_quote(item=make_line_item(quantity=Decimal("6000"), unit_price=Decimal("257.50")))
    pr = make_pr(make_pr_line(quantity=Decimal("8000"), max_price=Decimal("250")))
    comparison = compare(quote, pr)
    assert comparison.line is not None
    line = comparison.line
    assert line.quantity_difference == Decimal("-2000")
    assert line.quantity_difference_percent == Decimal("-25")
    assert line.unit_price_difference == Decimal("7.50")
    assert line.unit_price_difference_percent == Decimal("3.0")
