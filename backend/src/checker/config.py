"""Environment-backed settings. Secrets stay in the environment, never in code."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from checker.paths import backend_root

DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MAX_RETRIES = 2

ENV_FILE_ENV = "ENV_FILE"
DEFAULT_ENV_FILE_NAME = ".env"

logger = logging.getLogger(__name__)

_loaded_env_files: set[Path] = set()


class ConfigError(ValueError):
    """A required environment variable is missing or invalid."""


def default_env_file() -> Path:
    configured = os.environ.get(ENV_FILE_ENV, "").strip()
    if configured:
        return Path(configured)
    return backend_root() / DEFAULT_ENV_FILE_NAME


def load_env_file(path: Path | None = None) -> Path | None:
    """Populate the environment from a local `.env` file, once, without overriding it.

    The hosted deployment is given real environment variables and has no `.env`, so this is
    a local convenience: variables that already exist always win, and a missing file is not
    an error. Set `ENV_FILE` to point at a different file; tests point it at nothing so a
    developer's file never leaks into a test run.
    """
    target = (path or default_env_file()).resolve()
    if target in _loaded_env_files:
        return target
    _loaded_env_files.add(target)
    if not target.is_file():
        return None
    load_dotenv(target, override=False)
    logger.info("loaded environment variables from %s", target)
    return target


class LlmSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_url: str
    model: str
    api_key: str = Field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0, le=DEFAULT_MAX_RETRIES)
    reasoning_effort: str | None = None


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip().lower()
    return value or None


def _positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return value


def _retry_count(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a whole number") from exc
    if value < 0:
        raise ConfigError(f"{name} must not be negative")
    if value > DEFAULT_MAX_RETRIES:
        raise ConfigError(f"{name} must be at most {DEFAULT_MAX_RETRIES}")
    return value


def load_llm_settings() -> LlmSettings:
    return LlmSettings(
        base_url=_required("OPENROUTER_BASE_URL"),
        model=_required("OPENROUTER_MODEL"),
        api_key=_required("OPENROUTER_API_KEY"),
        timeout_seconds=_positive_float("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        max_retries=_retry_count("LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES),
        reasoning_effort=_optional("LLM_REASONING_EFFORT"),
    )
