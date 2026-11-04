from __future__ import annotations

import pytest

from checker.rules import RulesConfigError, load_rules
from checker.schemas import Severity


def test_rules_load_from_yaml(rules) -> None:
    assert rules.ruleset == "supplier-rules"
    assert rules.currency == "BDT"
    assert len(rules.rules) == 12


def test_rule_ids_are_the_documented_ones(rules) -> None:
    assert [rule.id for rule in rules.reject_rules] == [
        "REJ-01",
        "REJ-02",
        "REJ-03",
        "REJ-04",
        "REJ-05",
    ]
    assert [rule.id for rule in rules.needs_person_rules] == [
        "NP-01",
        "NP-02",
        "NP-03",
        "NP-04",
        "NP-05",
        "NP-06",
        "NP-07",
    ]
    assert all(rule.severity is Severity.REJECT for rule in rules.reject_rules)


def test_thresholds_come_from_the_file(rules) -> None:
    thresholds = rules.thresholds
    assert str(thresholds.price_over_max_percent) == "3"
    assert str(thresholds.advance_max_percent) == "20"
    assert thresholds.delivery_reject_days == 45
    assert str(thresholds.quantity_gap_percent) == "5"
    assert thresholds.payment_min_days == 30
    assert thresholds.payment_max_days == 60
    assert str(thresholds.vat_percent) == "15"
    assert thresholds.validity_min_days == 30
    assert str(thresholds.late_penalty_min_percent_per_week) == "0.5"
    assert str(thresholds.arithmetic_tolerance_bdt) == "0.01"


def test_missing_rules_file_is_a_setup_error(tmp_path) -> None:
    with pytest.raises(RulesConfigError):
        load_rules(tmp_path / "missing.yaml")
