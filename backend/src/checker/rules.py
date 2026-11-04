"""Load the company rules file and expose it as typed data.

Thresholds exist only in `rules/company_rules.yaml`. Check functions take them from
:class:`Thresholds`; they never contain a number themselves.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from checker.paths import backend_root
from checker.schemas import Severity

DEFAULT_RULES_PATH = Path("rules") / "company_rules.yaml"
RULES_PATH_ENV = "RULES_PATH"


class RulesConfigError(ValueError):
    """The rules file is missing or malformed. This is a setup error, not a document one."""


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    price_over_max_percent: Decimal
    advance_max_percent: Decimal
    delivery_reject_days: int
    delivery_review_min_days: int
    delivery_review_max_days: int
    quantity_gap_percent: Decimal
    payment_min_days: int
    payment_max_days: int
    vat_percent: Decimal
    validity_min_days: int
    late_penalty_min_percent_per_week: Decimal
    arithmetic_tolerance_bdt: Decimal


class Rule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    severity: Severity
    title: str


class RuleSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ruleset: str
    version: int
    currency: str
    thresholds: Thresholds
    rules: tuple[Rule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> RuleSet:
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule IDs must be unique")
        return self

    def rule(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise RulesConfigError(f"rule {rule_id} is not defined in the rules file")

    @property
    def reject_rules(self) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.severity is Severity.REJECT)

    @property
    def needs_person_rules(self) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.severity is Severity.NEEDS_PERSON)


def default_rules_path() -> Path:
    configured = os.environ.get(RULES_PATH_ENV)
    if configured:
        return Path(configured)
    return backend_root() / DEFAULT_RULES_PATH


def load_rules(path: Path | None = None) -> RuleSet:
    rules_path = path or default_rules_path()
    try:
        text = rules_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RulesConfigError(f"cannot read rules file: {rules_path}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RulesConfigError(f"rules file is not valid YAML: {rules_path}") from exc
    if not isinstance(data, dict):
        raise RulesConfigError(f"rules file must contain a mapping: {rules_path}")
    try:
        return RuleSet.model_validate(data)
    except ValueError as exc:
        raise RulesConfigError(f"rules file does not match the schema: {rules_path}") from exc
