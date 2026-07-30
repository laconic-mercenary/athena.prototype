"""Output contract for the report committee."""

from __future__ import annotations

from pydantic import BaseModel


class ReportOutput(BaseModel):
    directory: str          # the directory that was inventoried
    summary: str            # one short paragraph
    table_markdown: str     # a markdown table: | extension | count |
    total_files: int        # total files counted

    def render_full(self) -> str:
        """Full consumption view (R5). This is the terminal committee, so this is the report."""
        return (
            f"# Inventory — {self.directory}\n\n"
            f"{self.summary}\n\n"
            f"{self.table_markdown}\n\n"
            f"Total: {self.total_files}"
        )

    def render_digest(self) -> str:
        """Compact view for the gate (R4)."""
        return f"Report for {self.directory}: {self.total_files} files. {self.summary}"
