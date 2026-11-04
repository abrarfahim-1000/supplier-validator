"""Hosted API: a thin FastAPI layer over the per-document checker graph."""

from __future__ import annotations

from api.app import create_app

__all__ = ["create_app"]
