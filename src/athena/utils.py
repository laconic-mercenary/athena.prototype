"""Shared utility functions."""

from __future__ import annotations

from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


def new_short_id() -> str:
    return uuid4().hex[:8]
