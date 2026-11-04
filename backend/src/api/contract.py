"""Export the OpenAPI contract that the frontend generates its types from.

Run it after any change to the API models or routes:

    .venv/Scripts/python.exe -m api.contract

The output is committed; the frontend never hand-writes these types. Exporting needs no
secrets, no rules file and no network: the app factory only reads non-secret defaults.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from api.app import create_app
from checker.paths import repo_root

CONTRACT_PATH = Path("contracts") / "openapi.json"


def export_contract(path: Path) -> Path:
    schema = create_app().openapi()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the OpenAPI contract to disk.")
    parser.add_argument("--output", type=Path, default=repo_root() / CONTRACT_PATH)
    args = parser.parse_args(argv)
    print(f"wrote {export_contract(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
