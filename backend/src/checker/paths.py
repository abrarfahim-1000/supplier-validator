"""Where the project's files live.

Everything is derived from this file, so commands work from any working directory.

- `backend_root()` holds `pyproject.toml`: `src/`, `tests/`, `evals/`, `rules/` and `data/`.
- `repo_root()` is the repository, one level above, which keeps the artefacts that are not
  owned by the backend: the OpenAPI contract the frontend generates its types from, and the
  hand-written `ground_truth.csv`.
"""

from __future__ import annotations

from pathlib import Path


def backend_root() -> Path:
    """The backend directory (`backend/`), derived from this file (`src/checker/paths.py`)."""
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    """The repository root, which holds the backend and the shared artefacts."""
    return backend_root().parent
