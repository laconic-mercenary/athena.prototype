"""Output contract for the scan committee."""

from __future__ import annotations

from pydantic import BaseModel


class ExtensionCount(BaseModel):
    extension: str   # e.g. ".py" (includes the dot, lowercase)
    count: int


class ScanOutput(BaseModel):
    directory: str                     # the resolved absolute path that was walked
    counts: list[ExtensionCount]       # one entry per requested extension (regular + hidden combined)
    total_files: int                   # total files matching any requested extension
    hidden_files: int = 0              # subset whose filename starts with '.'
    regular_files: int = 0             # subset whose filename does not start with '.'
    skipped: list[str] = []            # paths that could not be read

    def render_full(self) -> str:
        """Full consumption view for a downstream committee."""
        lines = [
            f"Directory: {self.directory}",
            f"Total files: {self.total_files} ({self.regular_files} regular, {self.hidden_files} hidden)",
            "Counts (regular + hidden combined):",
        ]
        lines += [f"  {c.extension}: {c.count}" for c in self.counts]
        if self.skipped:
            lines.append(f"Skipped ({len(self.skipped)}): " + ", ".join(self.skipped))
        return "\n".join(lines)

    def render_digest(self) -> str:
        """Compact view for the gate — summary + adequacy fields."""
        counts = ", ".join(f"{c.extension}:{c.count}" for c in self.counts)
        return (
            f"Scanned {self.directory}: {self.total_files} files "
            f"({self.regular_files} regular, {self.hidden_files} hidden) "
            f"[{counts}]; {len(self.skipped)} skipped"
        )
