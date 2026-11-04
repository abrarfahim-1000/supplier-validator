"""API settings taken from environment variables.

Defaults mirror `.env.example`. Real values are only ever read from the environment: nothing
is loaded from `.env` by the application, and nothing here is exposed to the frontend.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from checker.config import ConfigError

DEFAULT_MAX_PDFS = 20
DEFAULT_MAX_FILE_MB = 5
DEFAULT_MAX_CONCURRENT_JOBS = 2
DEFAULT_JOB_TTL_SECONDS = 3600
DEFAULT_JOB_TIMEOUT_SECONDS = 600
DEFAULT_RATE_LIMIT_JOBS = 10
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_ALLOWED_ORIGINS = ("http://localhost:5173",)

MAX_PDFS_ENV = "MAX_PDFS"
MAX_FILE_MB_ENV = "MAX_FILE_MB"
MAX_CONCURRENT_JOBS_ENV = "MAX_CONCURRENT_JOBS"
JOB_TTL_SECONDS_ENV = "JOB_TTL_SECONDS"
JOB_TIMEOUT_SECONDS_ENV = "JOB_TIMEOUT_SECONDS"
RATE_LIMIT_JOBS_ENV = "RATE_LIMIT_JOBS"
RATE_LIMIT_WINDOW_SECONDS_ENV = "RATE_LIMIT_WINDOW_SECONDS"
TEMP_DIR_ENV = "TEMP_DIR_BASE"
ALLOWED_ORIGINS_ENV = "ALLOWED_ORIGINS"

MEGABYTE = 1024 * 1024


class ApiSettings(BaseModel):
    """Everything the hosted job flow needs that is not a secret."""

    model_config = ConfigDict(frozen=True)

    max_pdfs: int
    max_file_bytes: int
    max_concurrent_jobs: int
    job_ttl_seconds: int
    job_timeout_seconds: int
    rate_limit_jobs: int
    rate_limit_window_seconds: int
    temp_dir_base: Path
    allowed_origins: tuple[str, ...]

    @property
    def max_file_mb(self) -> int:
        return self.max_file_bytes // MEGABYTE

    @classmethod
    def from_env(cls) -> ApiSettings:
        max_file_mb = _int(MAX_FILE_MB_ENV, DEFAULT_MAX_FILE_MB, minimum=1)
        return cls(
            max_pdfs=_int(MAX_PDFS_ENV, DEFAULT_MAX_PDFS, minimum=1),
            max_file_bytes=max_file_mb * MEGABYTE,
            max_concurrent_jobs=_int(
                MAX_CONCURRENT_JOBS_ENV, DEFAULT_MAX_CONCURRENT_JOBS, minimum=1
            ),
            job_ttl_seconds=_int(JOB_TTL_SECONDS_ENV, DEFAULT_JOB_TTL_SECONDS, minimum=0),
            job_timeout_seconds=_int(
                JOB_TIMEOUT_SECONDS_ENV, DEFAULT_JOB_TIMEOUT_SECONDS, minimum=1
            ),
            rate_limit_jobs=_int(RATE_LIMIT_JOBS_ENV, DEFAULT_RATE_LIMIT_JOBS, minimum=1),
            rate_limit_window_seconds=_int(
                RATE_LIMIT_WINDOW_SECONDS_ENV, DEFAULT_RATE_LIMIT_WINDOW_SECONDS, minimum=1
            ),
            temp_dir_base=_temp_dir_base(),
            allowed_origins=_allowed_origins(),
        )


def _int(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a whole number") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}")
    return value


def _temp_dir_base() -> Path:
    raw = os.environ.get(TEMP_DIR_ENV, "").strip()
    return Path(raw) if raw else Path(tempfile.gettempdir())


def _allowed_origins() -> tuple[str, ...]:
    raw = os.environ.get(ALLOWED_ORIGINS_ENV, "").strip()
    if not raw:
        return DEFAULT_ALLOWED_ORIGINS
    origins = tuple(origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip())
    if not origins:
        raise ConfigError(f"{ALLOWED_ORIGINS_ENV} must list at least one origin")
    if "*" in origins:
        raise ConfigError(f"{ALLOWED_ORIGINS_ENV} must list explicit origins, not '*'")
    return origins
