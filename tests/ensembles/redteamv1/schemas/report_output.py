"""Output contract for the reporting committee."""

from __future__ import annotations

from pydantic import BaseModel


class ReportOutput(BaseModel):
    target: str
    risk_rating: str  # "Critical" | "High" | "Medium" | "Low"
    executive_summary: str
    flags_found: dict[str, str] = {}
    techniques_confirmed: list[str] = []
    findings_markdown: str
    recommendations_markdown: str

    def render_full(self) -> str:
        lines = [
            f"# Red Team Report — {self.target}",
            f"Risk Rating: {self.risk_rating}",
            "",
            "## Executive Summary",
            self.executive_summary,
        ]
        if self.flags_found:
            lines += ["", "## Flags"]
            for name, val in self.flags_found.items():
                lines.append(f"- **{name}**: `{val}`")
        if self.techniques_confirmed:
            lines += ["", "## MITRE ATT&CK Techniques Confirmed"]
            for t in self.techniques_confirmed:
                lines.append(f"- {t}")
        lines += [
            "",
            "## Findings",
            self.findings_markdown,
            "",
            "## Recommendations",
            self.recommendations_markdown,
        ]
        return "\n".join(lines)

    def render_digest(self) -> str:
        flags = list(self.flags_found.keys())
        return (
            f"{self.target} — {self.risk_rating} risk. "
            f"Flags: {', '.join(flags) if flags else 'none'}. "
            f"Techniques: {', '.join(self.techniques_confirmed[:4])}."
        )
