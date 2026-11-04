from __future__ import annotations

import json

from api.contract import export_contract
from checker.paths import repo_root

COMMITTED = repo_root() / "contracts" / "openapi.json"


def _schema(tmp_path) -> dict:
    path = export_contract(tmp_path / "openapi.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_committed_contract_matches_the_app(tmp_path) -> None:
    assert COMMITTED.is_file(), "run `python -m api.contract` and commit contracts/openapi.json"

    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))

    assert _schema(tmp_path) == committed


def test_contract_covers_the_whole_job_flow(tmp_path) -> None:
    schema = _schema(tmp_path)

    assert set(schema["paths"]) == {
        "/health",
        "/jobs",
        "/jobs/{job_id}",
        "/jobs/{job_id}/results",
    }
    schemas = schema["components"]["schemas"]
    assert "DocumentResult" in schemas
    assert "JobStatusResponse" in schemas
    assert "ErrorResponse" in schemas
