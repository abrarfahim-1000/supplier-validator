from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from checker.config import (
    ConfigError,
    default_env_file,
    load_env_file,
    load_llm_settings,
)


@pytest.fixture(autouse=True)
def restore_environment() -> Iterator[None]:
    """Loading a `.env` writes to os.environ directly, so put it back afterwards."""
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


def set_llm_env(monkeypatch, **overrides: str) -> None:
    for name in (
        "OPENROUTER_BASE_URL",
        "OPENROUTER_MODEL",
        "OPENROUTER_API_KEY",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        "LLM_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    values = {
        "OPENROUTER_BASE_URL": "https://example.invalid/v1",
        "OPENROUTER_MODEL": "test-model",
        "OPENROUTER_API_KEY": "test-key",
    }
    values.update(overrides)
    for name, value in values.items():
        if value:
            monkeypatch.setenv(name, value)


def test_settings_come_from_the_environment(monkeypatch) -> None:
    set_llm_env(monkeypatch)

    settings = load_llm_settings()

    assert settings.base_url == "https://example.invalid/v1"
    assert settings.model == "test-model"
    assert settings.api_key == "test-key"
    assert settings.timeout_seconds == 60
    assert settings.max_retries == 2


def test_api_key_is_hidden_from_repr(monkeypatch) -> None:
    set_llm_env(monkeypatch)

    assert "test-key" not in repr(load_llm_settings())


def test_missing_required_setting_is_a_setup_error(monkeypatch) -> None:
    set_llm_env(monkeypatch, OPENROUTER_API_KEY="")

    with pytest.raises(ConfigError) as excinfo:
        load_llm_settings()
    assert "OPENROUTER_API_KEY" in str(excinfo.value)


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_timeout_is_a_setup_error(monkeypatch, value: str) -> None:
    set_llm_env(monkeypatch, LLM_TIMEOUT_SECONDS=value)

    with pytest.raises(ConfigError):
        load_llm_settings()


@pytest.mark.parametrize("value", ["-1", "3", "many"])
def test_invalid_retry_count_is_a_setup_error(monkeypatch, value: str) -> None:
    set_llm_env(monkeypatch, LLM_MAX_RETRIES=value)

    with pytest.raises(ConfigError):
        load_llm_settings()


def test_retry_count_may_be_zero(monkeypatch) -> None:
    set_llm_env(monkeypatch, LLM_MAX_RETRIES="0")

    assert load_llm_settings().max_retries == 0


def test_reasoning_effort_is_unset_by_default(monkeypatch) -> None:
    set_llm_env(monkeypatch)

    assert load_llm_settings().reasoning_effort is None


def test_reasoning_effort_is_read_from_the_environment(monkeypatch) -> None:
    set_llm_env(monkeypatch, LLM_REASONING_EFFORT=" NONE ")

    assert load_llm_settings().reasoning_effort == "none"


def test_env_file_is_loaded(monkeypatch, tmp_path) -> None:
    path = tmp_path / "local.env"
    path.write_text("SDC_TEST_LOAD_ONLY=from-file\n", encoding="utf-8")
    monkeypatch.delenv("SDC_TEST_LOAD_ONLY", raising=False)

    assert load_env_file(path) == path.resolve()
    assert os.environ["SDC_TEST_LOAD_ONLY"] == "from-file"


def test_real_environment_wins_over_the_env_file(monkeypatch, tmp_path) -> None:
    path = tmp_path / "local.env"
    path.write_text("SDC_TEST_LOAD_ONLY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("SDC_TEST_LOAD_ONLY", "from-environment")

    load_env_file(path)

    assert os.environ["SDC_TEST_LOAD_ONLY"] == "from-environment"


def test_missing_env_file_is_not_an_error(tmp_path) -> None:
    assert load_env_file(tmp_path / "absent.env") is None


def test_env_file_location_is_configurable(monkeypatch, tmp_path) -> None:
    configured = tmp_path / "custom.env"
    monkeypatch.setenv("ENV_FILE", str(configured))

    assert default_env_file() == configured
