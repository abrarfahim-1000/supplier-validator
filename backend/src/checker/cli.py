"""Run the checker over local documents and print each decision.

This is an auxiliary to `evals/run_eval.py`: the harness scores against `ground_truth.csv`,
while this only runs the pipeline and reports what every document decided. Useful while
developing, or to inspect one directory of documents without ground truth at all.

    .venv/Scripts/python.exe -m checker.cli
    .venv/Scripts/python.exe -m checker.cli --data-dir some/folder

Exit codes: 0 when every document was processed (whatever it decided), 2 when the inputs or
the configuration are unusable.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from checker.config import ConfigError, load_env_file, load_llm_settings
from checker.graph import run_document
from checker.parse import Completer, build_completer
from checker.paths import backend_root
from checker.purchase_request import PurchaseRequestError, load_purchase_request_csv
from checker.rules import RulesConfigError, RuleSet, load_rules
from checker.schemas import Decision, DocumentResult

PURCHASE_REQUEST_FILENAME = "purchase-request.csv"


class CliSetupError(ValueError):
    """The inputs are missing or unusable. Not a document outcome."""


def discover_documents(data_dir: Path) -> list[Path]:
    if not data_dir.is_dir():
        raise CliSetupError(f"no such directory: {data_dir}")
    documents = sorted(data_dir.glob("*.pdf"))
    if not documents:
        raise CliSetupError(f"no PDF documents in {data_dir}")
    return documents


def format_result(result: DocumentResult) -> str:
    lines = [f"{result.source_filename}: {result.decision.name}"]
    if result.processing_failure and result.failure_detail:
        lines.append(f"  processing failure: {result.failure_detail}")
    for reason in result.reasons:
        tag = reason.rule_id or reason.code
        lines.append(f"  [{tag}] {reason.title}: {reason.detail}")
    if not result.reasons:
        lines.append("  no rule triggered")
    return "\n".join(lines)


def run_documents(
    *,
    data_dir: Path,
    purchase_request_path: Path,
    rules: RuleSet,
    completer: Completer,
    on_result: Callable[[int, int, DocumentResult], None] | None = None,
) -> list[DocumentResult]:
    """One document at a time, in filename order, so a slow endpoint stays predictable."""
    documents = discover_documents(data_dir)
    purchase_request = load_purchase_request_csv(purchase_request_path)
    results: list[DocumentResult] = []
    for index, pdf_path in enumerate(documents, start=1):
        result = run_document(
            pdf_path=pdf_path,
            document_id=pdf_path.stem,
            purchase_request=purchase_request,
            rules=rules,
            complete=completer,
            source_filename=pdf_path.name,
        )
        results.append(result)
        if on_result is not None:
            on_result(index, len(documents), result)
    return results


def format_summary(results: Sequence[DocumentResult]) -> str:
    counts = Counter(result.decision for result in results)
    parts = [
        f"{decision.name} {counts[decision]}"
        for decision in (Decision.APPROVE, Decision.REJECT, Decision.NEEDS_PERSON)
    ]
    failed = sum(result.processing_failure for result in results)
    tail = f", processing failures {failed}" if failed else ""
    noun = "document" if len(results) == 1 else "documents"
    return f"\n{len(results)} {noun}: " + ", ".join(parts) + tail


def main(
    argv: Sequence[str] | None = None,
    *,
    completer: Completer | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m checker.cli",
        description="Run every PDF in a directory through the checker and print each decision.",
    )
    parser.add_argument("--data-dir", type=Path, default=backend_root() / "data")
    parser.add_argument(
        "--purchase-request",
        type=Path,
        default=None,
        help=f"default: <data-dir>/{PURCHASE_REQUEST_FILENAME}",
    )
    parser.add_argument(
        "--rules", type=Path, default=None, help="default: rules/company_rules.yaml"
    )
    args = parser.parse_args(argv)

    data_dir: Path = args.data_dir
    purchase_request_path: Path = args.purchase_request or data_dir / PURCHASE_REQUEST_FILENAME

    try:
        load_env_file()
        rules = load_rules(args.rules)
        active = completer if completer is not None else build_completer(load_llm_settings())
        results = run_documents(
            data_dir=data_dir,
            purchase_request_path=purchase_request_path,
            rules=rules,
            completer=active,
            on_result=lambda index, total, result: print(
                f"[{index}/{total}] {format_result(result)}", flush=True
            ),
        )
    except (CliSetupError, RulesConfigError, PurchaseRequestError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(format_summary(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
