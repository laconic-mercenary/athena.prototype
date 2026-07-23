"""Output contract for the scan committee."""

from __future__ import annotations

from pydantic import BaseModel


class ExtensionCount(BaseModel):
    extension: str   # e.g. ".py" (includes the dot, lowercase)
    count: int


class ScanOutput(BaseModel):
    directory: str                     # the resolved absolute path that was walked
    counts: list[ExtensionCount]       # one entry per requested extension
    total_files: int                   # total files matching any requested extension
    skipped: list[str] = []            # paths that could not be read
