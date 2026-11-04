from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from evals.run_eval import (
    EvalSetupError,
    Expected,
    PackOutcome,
    discover_packs,
    evaluate,
    format_report,
    load_ground_truth,
    main,
    validate_rule_ids,
)

from canned import SYNTHETIC_LINES, extraction_payload
from checker.schemas import Decision, DocumentResult, Reason
from pdf_factory import write_pdf

PURCHASE_REQUEST = (
    "PR number,Item,Description,Unit,Quantity requested,Maximum unit price (BDT)\n"
    'PR-0000-001,A,"Blue denim roll, 12 oz",metre,100,10.00\n'
)

GROUND_TRUTH_HEADER = "pack,decision,rule_ids,notes\n"


def write_ground_truth(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["pack", "decision", "rule_ids", "notes"])
        writer.writerows(rows)


def write_data_dir(path: Path, packs: list[str]) -> None:
    path.mkdir()
    (path / "purchase-request.csv").write_text(PURCHASE_REQUEST, encoding="utf-8")
    for pack in packs:
        write_pdf(path / f"{pack}.pdf", SYNTHETIC_LINES)


def make_result(
    pack: str,
    decision: Decision,
    rule_ids: tuple[str, ...] = (),
    *,
    processing_failure: bool = False,
    failure_detail: str | None = None,
) -> DocumentResult:
    reasons = [
        Reason(code=rule_id, rule_id=rule_id, title=f"Rule {rule_id}", detail="detail")
        for rule_id in rule_ids
    ]
    return DocumentResult(
        document_id=pack,
        source_filename=f"{pack}.pdf",
        decision=decision,
        reasons=reasons,
        checks=[],
        processing_failure=processing_failure,
        failure_detail=failure_detail,
    )


def make_expected(
    pack: str,
    decision: str = "APPROVE",
    rule_ids: tuple[str, ...] = (),
    notes: str = "note",
) -> Expected:
    return Expected(
        pack=pack,
        decision=Decision[decision],
        rule_ids=rule_ids,
        notes=notes,
    )


def test_ground_truth_rows_are_loaded(tmp_path) -> None:
    path = tmp_path / "ground_truth.csv"
    write_ground_truth(
        path,
        [
            ("supplier-pack-01", "APPROVE", "", "clean"),
            ("supplier-pack-10", "REJECT", "REJ-05;NP-05", "two hits"),
        ],
    )

    expected = load_ground_truth(path)

    assert [row.pack for row in expected] == ["supplier-pack-01", "supplier-pack-10"]
    assert expected[0].decision is Decision.APPROVE
    assert expected[0].rule_ids == ()
    assert expected[1].decision is Decision.REJECT
    assert expected[1].rule_ids == ("REJ-05", "NP-05")
    assert expected[1].notes == "two hits"


def test_unknown_decision_is_a_setup_error(tmp_path) -> None:
    path = tmp_path / "ground_truth.csv"
    write_ground_truth(path, [("supplier-pack-01", "MAYBE", "", "")])

    with pytest.raises(EvalSetupError) as excinfo:
        load_ground_truth(path)
    assert "unknown decision" in str(excinfo.value)


def test_duplicate_pack_is_a_setup_error(tmp_path) -> None:
    path = tmp_path / "ground_truth.csv"
    write_ground_truth(
        path,
        [("supplier-pack-01", "APPROVE", "", ""), ("supplier-pack-01", "REJECT", "", "")],
    )

    with pytest.raises(EvalSetupError) as excinfo:
        load_ground_truth(path)
    assert "more than once" in str(excinfo.value)


def test_duplicate_rule_ids_are_a_setup_error(tmp_path) -> None:
    path = tmp_path / "ground_truth.csv"
    write_ground_truth(path, [("supplier-pack-01", "REJECT", "REJ-01;REJ-01", "")])

    with pytest.raises(EvalSetupError) as excinfo:
        load_ground_truth(path)
    assert "duplicate rule IDs" in str(excinfo.value)


def test_empty_ground_truth_is_a_setup_error(tmp_path) -> None:
    path = tmp_path / "ground_truth.csv"
    path.write_text(GROUND_TRUTH_HEADER, encoding="utf-8")

    with pytest.raises(EvalSetupError):
        load_ground_truth(path)


def test_unknown_rule_id_in_ground_truth_is_a_setup_error(rules) -> None:
    expected = [make_expected("supplier-pack-01", "REJECT", ("REJ-99",))]

    with pytest.raises(EvalSetupError) as excinfo:
        validate_rule_ids(expected, rules)
    assert "REJ-99" in str(excinfo.value)


def test_outcome_compares_decisions_and_rule_sets() -> None:
    expected = make_expected("supplier-pack-10", "REJECT", ("REJ-05", "NP-05"))
    reordered = make_result("supplier-pack-10", Decision.REJECT, ("NP-05", "REJ-05"))
    assert PackOutcome(expected, reordered).passed

    missing = PackOutcome(expected, make_result("supplier-pack-10", Decision.REJECT, ("REJ-05",)))
    assert missing.decision_matches
    assert not missing.rule_ids_match
    assert not missing.passed

    wrong = PackOutcome(expected, make_result("supplier-pack-10", Decision.NEEDS_PERSON))
    assert not wrong.decision_matches
    assert not wrong.passed


def test_report_has_the_headline_and_status_column() -> None:
    outcomes = [
        PackOutcome(
            make_expected("supplier-pack-01", "APPROVE"),
            make_result("supplier-pack-01", Decision.APPROVE),
        ),
        PackOutcome(
            make_expected("supplier-pack-02", "REJECT", ("REJ-01",)),
            make_result("supplier-pack-02", Decision.NEEDS_PERSON, ("NP-01",)),
        ),
    ]

    report = format_report(outcomes)

    assert "Decision accuracy: 1/2 (50.0%)" in report
    assert "Rule ID matches: 1/2" in report
    assert "MISMATCH" in report
    assert "All packs match ground truth." not in report


def test_report_lists_the_reasons_for_a_mismatch() -> None:
    expected = make_expected("supplier-pack-04", "NEEDS_PERSON", ("NP-01",))
    result = make_result(
        "supplier-pack-04",
        Decision.NEEDS_PERSON,
        ("REJ-01",),
        processing_failure=True,
        failure_detail="the model was unavailable",
    )

    report = format_report([PackOutcome(expected, result)])

    assert "supplier-pack-04" in report
    assert "[REJ-01] Rule REJ-01: detail" in report
    assert "processing failure: the model was unavailable" in report
    assert "expected rules: NP-01 | actual rules: REJ-01" in report


def test_report_says_when_everything_matches() -> None:
    outcomes = [
        PackOutcome(
            make_expected("supplier-pack-01"),
            make_result("supplier-pack-01", Decision.APPROVE),
        )
    ]

    report = format_report(outcomes)

    assert "Decision accuracy: 1/1 (100.0%)" in report
    assert "All packs match ground truth." in report


def test_discover_packs_follows_ground_truth_order(tmp_path) -> None:
    write_data_dir(tmp_path / "data", ["supplier-pack-02", "supplier-pack-01"])
    expected = [make_expected("supplier-pack-01"), make_expected("supplier-pack-02")]

    packs = discover_packs(tmp_path / "data", expected)

    assert [path.stem for path in packs] == ["supplier-pack-01", "supplier-pack-02"]


def test_missing_pdf_is_a_setup_error(tmp_path) -> None:
    write_data_dir(tmp_path / "data", ["supplier-pack-01"])

    with pytest.raises(EvalSetupError) as excinfo:
        discover_packs(
            tmp_path / "data",
            [make_expected("supplier-pack-01"), make_expected("supplier-pack-02")],
        )
    assert "supplier-pack-02" in str(excinfo.value)


def test_extra_pdf_without_ground_truth_is_a_setup_error(tmp_path) -> None:
    write_data_dir(tmp_path / "data", ["supplier-pack-01", "supplier-pack-02"])

    with pytest.raises(EvalSetupError) as excinfo:
        discover_packs(tmp_path / "data", [make_expected("supplier-pack-01")])
    assert "supplier-pack-02" in str(excinfo.value)


def test_missing_data_dir_is_a_setup_error(tmp_path) -> None:
    with pytest.raises(EvalSetupError):
        discover_packs(tmp_path / "nope", [make_expected("supplier-pack-01")])


def test_evaluate_runs_every_pack_with_the_injected_completer(tmp_path, rules) -> None:
    data_dir = tmp_path / "data"
    write_data_dir(data_dir, ["supplier-pack-01", "supplier-pack-02"])
    ground_truth = tmp_path / "ground_truth.csv"
    write_ground_truth(
        ground_truth,
        [
            ("supplier-pack-01", "APPROVE", "", "clean"),
            ("supplier-pack-02", "APPROVE", "", "clean"),
        ],
    )

    def complete(messages) -> str:
        return json.dumps(extraction_payload())

    outcomes = evaluate(
        data_dir=data_dir,
        ground_truth_path=ground_truth,
        rules=rules,
        completer=complete,
    )

    assert [outcome.expected.pack for outcome in outcomes] == [
        "supplier-pack-01",
        "supplier-pack-02",
    ]
    assert all(outcome.passed for outcome in outcomes)
    assert "Decision accuracy: 2/2 (100.0%)" in format_report(outcomes)


def test_evaluate_counts_a_decision_mismatch(tmp_path, rules) -> None:
    data_dir = tmp_path / "data"
    write_data_dir(data_dir, ["supplier-pack-01"])
    ground_truth = tmp_path / "ground_truth.csv"
    write_ground_truth(ground_truth, [("supplier-pack-01", "REJECT", "REJ-01", "")])

    outcomes = evaluate(
        data_dir=data_dir,
        ground_truth_path=ground_truth,
        rules=rules,
        completer=lambda messages: json.dumps(extraction_payload()),
    )

    assert not outcomes[0].passed
    assert "Decision accuracy: 0/1 (0.0%)" in format_report(outcomes)


def test_main_returns_a_setup_error_code_without_a_data_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "test-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    # The host exports a broken SSL_CERT_FILE; the client is never called here.
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    code = main(["--data-dir", str(tmp_path / "missing")])

    assert code == 2
