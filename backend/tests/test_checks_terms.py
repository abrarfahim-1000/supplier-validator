from __future__ import annotations

from decimal import Decimal

from builders import by_code, compare, f, make_quote
from checker.checks import run_all_checks
from checker.schemas import CheckStatus, FieldStatus


def checks_for(quote, rules):
    return run_all_checks(quote, compare(quote), rules)


def ambiguous(note: str = "ambiguous value"):
    return f(None).model_copy(
        update={"status": FieldStatus.AMBIGUOUS, "snippet": "quoted text", "note": note}
    )


def test_advance_boundaries(rules) -> None:
    at_limit = checks_for(make_quote(advance=Decimal("20")), rules)
    assert by_code(at_limit, "REJ-02").status is CheckStatus.PASS

    over = checks_for(make_quote(advance=Decimal("20.1")), rules)
    assert by_code(over, "REJ-02").status is CheckStatus.REJECT

    missing = checks_for(make_quote(advance=None), rules)
    assert by_code(missing, "REJ-02").status is CheckStatus.NEEDS_PERSON

    unreadable = make_quote(advance=Decimal("10"))
    unreadable = unreadable.model_copy(
        update={"terms": unreadable.terms.model_copy(update={"advance_percent": ambiguous()})}
    )
    assert by_code(checks_for(unreadable, rules), "REJ-02").status is CheckStatus.NEEDS_PERSON


def test_payment_terms_window(rules) -> None:
    assert (
        by_code(checks_for(make_quote(payment_days=Decimal("30")), rules), "NP-03").status
        is CheckStatus.PASS
    )
    assert (
        by_code(checks_for(make_quote(payment_days=Decimal("60")), rules), "NP-03").status
        is CheckStatus.PASS
    )
    assert (
        by_code(checks_for(make_quote(payment_days=Decimal("29")), rules), "NP-03").status
        is CheckStatus.NEEDS_PERSON
    )
    assert (
        by_code(checks_for(make_quote(payment_days=Decimal("61")), rules), "NP-03").status
        is CheckStatus.NEEDS_PERSON
    )
    unclear = make_quote().model_copy(
        update={"terms": make_quote().terms.model_copy(update={"payment_days": ambiguous()})}
    )
    assert by_code(checks_for(unclear, rules), "NP-03").status is CheckStatus.NEEDS_PERSON


def test_delivery_reject_and_review_bands(rules) -> None:
    checks_44 = checks_for(make_quote(delivery_days=Decimal("44")), rules)
    assert by_code(checks_44, "REJ-05").status is CheckStatus.PASS
    assert by_code(checks_44, "NP-04").status is CheckStatus.NEEDS_PERSON

    checks_45 = checks_for(make_quote(delivery_days=Decimal("45")), rules)
    assert by_code(checks_45, "REJ-05").status is CheckStatus.PASS
    assert by_code(checks_45, "NP-04").status is CheckStatus.NEEDS_PERSON

    checks_46 = checks_for(make_quote(delivery_days=Decimal("46")), rules)
    assert by_code(checks_46, "REJ-05").status is CheckStatus.REJECT
    assert by_code(checks_46, "NP-04").status is CheckStatus.PASS

    checks_30 = checks_for(make_quote(delivery_days=Decimal("30")), rules)
    assert by_code(checks_30, "NP-04").status is CheckStatus.PASS

    checks_31 = checks_for(make_quote(delivery_days=Decimal("31")), rules)
    assert by_code(checks_31, "NP-04").status is CheckStatus.NEEDS_PERSON

    missing = checks_for(make_quote(delivery_days=None), rules)
    assert by_code(missing, "REJ-05").status is CheckStatus.NEEDS_PERSON
    assert by_code(missing, "NP-04").status is CheckStatus.NEEDS_PERSON


def test_missing_penalty_clause_rejects(rules) -> None:
    quote = make_quote(penalty_present=False)
    checks = checks_for(quote, rules)
    assert by_code(checks, "REJ-03").status is CheckStatus.REJECT
    assert by_code(checks, "EDGE-PENALTY").status is CheckStatus.PASS


def test_present_penalty_clause_passes(rules) -> None:
    checks = checks_for(make_quote(), rules)
    assert by_code(checks, "REJ-03").status is CheckStatus.PASS


def test_unverified_penalty_clause_is_needs_person(rules) -> None:
    quote = make_quote().model_copy(
        update={
            "terms": make_quote().terms.model_copy(
                update={
                    "late_penalty_clause": f(None).model_copy(
                        update={
                            "status": FieldStatus.UNVERIFIED,
                            "snippet": "invented clause",
                            "note": "snippet not found",
                        }
                    )
                }
            )
        }
    )
    assert by_code(checks_for(quote, rules), "REJ-03").status is CheckStatus.NEEDS_PERSON


def test_penalty_minimum_and_basis(rules) -> None:
    at_minimum = checks_for(make_quote(penalty=Decimal("0.5")), rules)
    assert by_code(at_minimum, "EDGE-PENALTY").status is CheckStatus.PASS

    below = checks_for(make_quote(penalty=Decimal("0.49")), rules)
    assert by_code(below, "EDGE-PENALTY").status is CheckStatus.NEEDS_PERSON

    no_basis = checks_for(make_quote(penalty_basis=False), rules)
    assert by_code(no_basis, "EDGE-PENALTY").status is CheckStatus.NEEDS_PERSON

    unverified_basis = checks_for(make_quote(penalty_basis=None), rules)
    assert by_code(unverified_basis, "EDGE-PENALTY").status is CheckStatus.NEEDS_PERSON


def test_tin_and_bin(rules) -> None:
    present = checks_for(make_quote(), rules)
    assert by_code(present, "REJ-04").status is CheckStatus.PASS

    no_tin = checks_for(make_quote(tin=None), rules)
    assert by_code(no_tin, "REJ-04").status is CheckStatus.REJECT

    no_bin = checks_for(make_quote(bin_value=None), rules)
    assert by_code(no_bin, "REJ-04").status is CheckStatus.REJECT

    unreadable = make_quote().model_copy(update={"tin": ambiguous("unreadable TIN")})
    assert by_code(checks_for(unreadable, rules), "REJ-04").status is CheckStatus.NEEDS_PERSON


def test_vat_must_be_separate_at_fifteen_percent(rules) -> None:
    assert by_code(checks_for(make_quote(), rules), "NP-05").status is CheckStatus.PASS
    no_vat = checks_for(make_quote(vat_rate=None, vat_amount=None, vat_statement=None), rules)
    assert by_code(no_vat, "NP-05").status is CheckStatus.NEEDS_PERSON

    wrong_rate = checks_for(make_quote(vat_rate=Decimal("14"), vat_amount=Decimal("140")), rules)
    assert by_code(wrong_rate, "NP-05").status is CheckStatus.NEEDS_PERSON

    no_amount = checks_for(make_quote(vat_amount=None), rules)
    assert by_code(no_amount, "NP-05").status is CheckStatus.NEEDS_PERSON


def test_validity_boundary(rules) -> None:
    assert (
        by_code(checks_for(make_quote(validity_days=Decimal("29")), rules), "NP-07").status
        is CheckStatus.NEEDS_PERSON
    )
    assert (
        by_code(checks_for(make_quote(validity_days=Decimal("30")), rules), "NP-07").status
        is CheckStatus.PASS
    )
    assert (
        by_code(checks_for(make_quote(validity_days=Decimal("31")), rules), "NP-07").status
        is CheckStatus.PASS
    )


def test_quantity_gap_boundary(rules) -> None:
    five_percent = make_quote()
    five_percent = five_percent.model_copy(
        update={
            "line_items": [
                five_percent.line_items[0].model_copy(update={"quantity": f(Decimal("105"))})
            ]
        }
    )
    assert by_code(checks_for(five_percent, rules), "NP-02").status is CheckStatus.PASS

    over = five_percent.model_copy(
        update={
            "line_items": [
                five_percent.line_items[0].model_copy(update={"quantity": f(Decimal("105.01"))})
            ]
        }
    )
    assert by_code(checks_for(over, rules), "NP-02").status is CheckStatus.NEEDS_PERSON
