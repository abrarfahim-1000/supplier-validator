from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from checker.rules import RuleSet, load_rules

NO_ENV_FILE = Path(tempfile.gettempdir()) / "sdc-tests-no-such.env"


@pytest.fixture(autouse=True)
def isolated_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the developer's `.env`; settings come from the test that needs them."""
    monkeypatch.setenv("ENV_FILE", str(NO_ENV_FILE))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


@pytest.fixture(scope="session")
def rules() -> Iterator[RuleSet]:
    yield load_rules()
