"""Score the pipeline against the hand-checked ground truth.

Run all packs found in the local (git-ignored) `data/` directory through the real
per-document graph, once each and sequentially, then compare the decision and the set of
triggered rule IDs with `ground_truth.csv`.

    .venv/Scripts/python.exe evals/run_eval.py

Exit codes: 0 when every pack matches, 1 when any pack differs, 2 when the evaluation
cannot run (missing data, bad ground truth, missing LLM settings).

This module never edits ground truth and never special-cases a pack. Mismatches are
printed with the decision reasons so the cause can be fixed in the pipeline.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from checker.config import ConfigError, load_env_file, load_llm_settings
from checker.graph import run_document
from checker.parse import Completer, build_completer
from checker.paths import backend_root, repo_root
from checker.purchase_request import PurchaseRequestError, load_purchase_request_csv
from checker.rules import RulesConfigError, RuleSet, load_rules
from checker.schemas import Decision, DocumentResult, Reason

PURCHASE_REQUEST_FILENAME = "purchase-request.csv"
GROUND_TRUTH_FILENAME = "ground_truth.csv"
PACK_GLOB = "supplier-pack-*.pdf"

DECISION_TOKENS = {decision.name: decision for decision in Decision}
PERCENT = Decimal(100)
TENTH = Decimal("0.1")


class EvalSetupError(ValueError):
    """The evaluation inputs are missing or inconsistent. Not a pack outcome."""


@dataclass(frozen=True)
class Expected:
    pack: str
    decision: Decision
    rule_ids: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class PackOutcome:
    expected: Expected
    result: DocumentResult

    @property
    def actual_rule_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for reason in self.result.reasons:
            if reason.rule_id and reason.rule_id not in seen:
                seen.append(reason.rule_id)
        return tuple(seen)

    @property
    def decision_matches(self) -> bool:
        return self.result.decision is self.expected.decision

    @property
    def rule_ids_match(self) -> bool:
        return set(self.actual_rule_ids) == set(self.expected.rule_ids)

    @property
    def passed(self) -> bool:
        return self.decision_matches and self.rule_ids_match


def load_ground_truth(path: Path) -> list[Expected]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise EvalSetupError(f"cannot read ground truth: {path}") from exc

    expected: list[Expected] = []
    seen: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        pack = (row.get("pack") or "").strip()
        if not pack:
            raise EvalSetupError(f"ground truth line {line_number}: 'pack' is empty")
        if pack in seen:
            raise EvalSetupError(f"ground truth lists pack {pack} more than once")
        seen.add(pack)
        token = (row.get("decision") or "").strip().upper()
        if token not in DECISION_TOKENS:
            raise EvalSetupError(
                f"ground truth line {line_number}: unknown decision {token!r}"
                " (expected APPROVE, REJECT or NEEDS_PERSON)"
            )
        rule_ids = tuple(
            value.strip() for value in (row.get("rule_ids") or "").split(";") if value.strip()
        )
        if len(set(rule_ids)) != len(rule_ids):
            raise EvalSetupError(f"ground truth line {line_number}: duplicate rule IDs for {pack}")
        expected.append(
            Expected(
                pack=pack,
                decision=DECISION_TOKENS[token],
                rule_ids=rule_ids,
                notes=(row.get("notes") or "").strip(),
            )
        )
    if not expected:
        raise EvalSetupError(f"ground truth has no rows: {path}")
    return expected


def discover_packs(data_dir: Path, expected: Sequence[Expected]) -> list[Path]:
    if not data_dir.is_dir():
        raise EvalSetupError(
            f"data directory not found: {data_dir}"
            " (copy the sample files into data/ as described in the README)"
        )
    present = {path.stem: path for path in sorted(data_dir.glob(PACK_GLOB))}
    missing = [row.pack for row in expected if row.pack not in present]
    if missing:
        raise EvalSetupError("ground truth lists packs with no PDF in data/: " + ", ".join(missing))
    extra = sorted(set(present) - {row.pack for row in expected})
    if extra:
        raise EvalSetupError("data/ contains packs with no ground truth row: " + ", ".join(extra))
    return [present[row.pack] for row in expected]


def validate_rule_ids(expected: Sequence[Expected], rules: RuleSet) -> None:
    known = {rule.id for rule in rules.rules}
    for row in expected:
        unknown = [rule_id for rule_id in row.rule_ids if rule_id not in known]
        if unknown:
            raise EvalSetupError(
                f"ground truth pack {row.pack} references unknown rule IDs: " + ", ".join(unknown)
            )


def evaluate(
    *,
    data_dir: Path,
    ground_truth_path: Path,
    rules: RuleSet,
    completer: Completer,
    progress: Callable[[str], None] | None = None,
) -> list[PackOutcome]:
    expected = load_ground_truth(ground_truth_path)
    validate_rule_ids(expected, rules)
    packs = discover_packs(data_dir, expected)
    purchase_request = load_purchase_request_csv(data_dir / PURCHASE_REQUEST_FILENAME)

    outcomes: list[PackOutcome] = []
    for index, (row, pdf_path) in enumerate(zip(expected, packs, strict=True), start=1):
        started = time.monotonic()
        result = run_document(
            pdf_path=pdf_path,
            document_id=row.pack,
            purchase_request=purchase_request,
            rules=rules,
            complete=completer,
            source_filename=pdf_path.name,
        )
        outcomes.append(PackOutcome(expected=row, result=result))
        if progress is not None:
            # Live progress matters: a slow free-tier endpoint otherwise looks like a hang.
            progress(
                f"[{index}/{len(packs)}] {row.pack}: {result.decision.name} "
                f"in {time.monotonic() - started:.1f}s"
            )
    return outcomes


def _decision_label(decision: Decision) -> str:
    return decision.name


def _rules_label(rule_ids: Sequence[str]) -> str:
    return ", ".join(rule_ids) if rule_ids else "none"


def _accuracy(hits: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    value = (Decimal(hits) / Decimal(total) * PERCENT).quantize(TENTH)
    return f"{value}%"


def _reason_line(reason: Reason) -> str:
    tag = reason.rule_id or reason.code
    return f"      [{tag}] {reason.title}: {reason.detail}"


def format_report(outcomes: Sequence[PackOutcome]) -> str:
    total = len(outcomes)
    decision_hits = sum(outcome.decision_matches for outcome in outcomes)
    rule_hits = sum(outcome.rule_ids_match for outcome in outcomes)

    lines = [
        "Supplier document checker - evaluation",
        f"Packs: {total}",
        f"Decision accuracy: {decision_hits}/{total} ({_accuracy(decision_hits, total)})",
        f"Rule ID matches: {rule_hits}/{total}",
        "",
        f"{'pack':<20} {'expected':<14} {'actual':<14} {'rule IDs expected':<22}"
        f" {'rule IDs actual':<22} status",
    ]
    for outcome in outcomes:
        lines.append(
            f"{outcome.expected.pack:<20} "
            f"{_decision_label(outcome.expected.decision):<14} "
            f"{_decision_label(outcome.result.decision):<14} "
            f"{_rules_label(outcome.expected.rule_ids):<22} "
            f"{_rules_label(outcome.actual_rule_ids):<22} "
            f"{'ok' if outcome.passed else 'MISMATCH'}"
        )

    mismatches = [outcome for outcome in outcomes if not outcome.passed]
    lines.append("")
    if not mismatches:
        lines.append("All packs match ground truth.")
        return "\n".join(lines)

    lines.append(f"Mismatches ({len(mismatches)})")
    for outcome in mismatches:
        result = outcome.result
        lines.append("")
        lines.append(outcome.expected.pack)
        lines.append(
            "  expected decision: "
            f"{_decision_label(outcome.expected.decision)}, "
            f"actual: {_decision_label(result.decision)}"
        )
        lines.append(
            f"  expected rules: {_rules_label(outcome.expected.rule_ids)} | "
            f"actual rules: {_rules_label(outcome.actual_rule_ids)}"
        )
        lines.append(f"  ground truth note: {outcome.expected.notes or 'none'}")
        if result.processing_failure and result.failure_detail:
            lines.append(f"  processing failure: {result.failure_detail}")
        if result.reasons:
            lines.append("  reasons:")
            lines.extend(_reason_line(reason) for reason in result.reasons)
        else:
            lines.append("  reasons: none (the document passed every check)")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run every local pack and compare it with ground_truth.csv."
    )
    parser.add_argument("--data-dir", type=Path, default=backend_root() / "data")
    parser.add_argument("--ground-truth", type=Path, default=repo_root() / GROUND_TRUTH_FILENAME)
    args = parser.parse_args(argv)

    try:
        load_env_file()
        rules = load_rules()
        completer = build_completer(load_llm_settings())
        outcomes = evaluate(
            data_dir=args.data_dir,
            ground_truth_path=args.ground_truth,
            rules=rules,
            completer=completer,
            progress=lambda line: print(line, file=sys.stderr, flush=True),
        )
    except (EvalSetupError, RulesConfigError, PurchaseRequestError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(format_report(outcomes))
    return 0 if all(outcome.passed for outcome in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
