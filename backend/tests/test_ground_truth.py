from __future__ import annotations

import csv

from checker.paths import backend_root, repo_root

DECISIONS = {"APPROVE", "REJECT", "NEEDS_PERSON"}


def ground_truth_rows() -> list[dict[str, str]]:
    path = repo_root() / "ground_truth.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_ground_truth_has_one_row_per_pack(rules) -> None:
    rows = ground_truth_rows()
    assert len(rows) == 10
    assert [row["pack"] for row in rows] == [f"supplier-pack-{index:02d}" for index in range(1, 11)]
    rule_ids = {rule.id for rule in rules.rules}
    for row in rows:
        assert row["decision"] in DECISIONS
        triggered = [value for value in row["rule_ids"].split(";") if value]
        assert set(triggered) <= rule_ids, row["pack"]
        assert row["notes"]


def test_ground_truth_packs_exist_when_sample_data_is_present() -> None:
    data_dir = backend_root() / "data"
    if not data_dir.is_dir():
        return
    packs = {path.stem for path in data_dir.glob("supplier-pack-*.pdf")}
    assert packs == {row["pack"] for row in ground_truth_rows()}
