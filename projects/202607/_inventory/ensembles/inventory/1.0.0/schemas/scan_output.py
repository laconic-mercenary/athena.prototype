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

    def render_full(self) -> str:
        """Full consumption view for a downstream committee (R5)."""
        lines = [f"Directory: {self.directory}", f"Total files: {self.total_files}", "Counts:"]
        lines += [f"  {c.extension}: {c.count}" for c in self.counts]
        if self.skipped:
            lines.append(f"Skipped ({len(self.skipped)}): " + ", ".join(self.skipped))
        return "\n".join(lines)

    def render_digest(self) -> str:
        """Compact view for the gate / consumes.optional (R4) — summary + adequacy fields."""
        counts = ", ".join(f"{c.extension}:{c.count}" for c in self.counts)
        return (
            f"Scanned {self.directory}: {self.total_files} files ({counts}); "
            f"{len(self.skipped)} skipped"
        )
