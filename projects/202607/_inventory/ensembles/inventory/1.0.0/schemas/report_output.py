"""Output contract for the report committee."""

from __future__ import annotations

from pydantic import BaseModel


class ReportOutput(BaseModel):
    directory: str          # the directory that was inventoried
    summary: str            # one short paragraph
    table_markdown: str     # a markdown table: | extension | count |
    total_files: int        # total files counted
