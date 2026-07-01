"""Artifact and run logging.

RunLogger owns a named logger (athena.run.<run_id>) with a FileHandler that
writes to artifacts/<run_id>/run.log. Lifecycle events propagate up to the
athena stream handler for stdout output automatically.
"""

from __future__ import annotations

import logging
from pathlib import Path
import json
from typing import TYPE_CHECKING

from athena.logging_setup import UTC_FORMATTER

if TYPE_CHECKING:
    from athena.schemas import PlanArtifact, ReportArtifact, RetrievalArtifact

_PRIORITY_LABEL = {
    "critical": "CRITICAL",
    "high":     "HIGH",
    "medium":   "MEDIUM",
    "low":      "LOW",
}


def render_plan_report(artifact: "PlanArtifact") -> str:
    """Render a PlanArtifact as a human-readable markdown report."""
    lines: list[str] = []

    lines += [
        "# Athena Engagement Plan",
        "",
        f"| | |",
        f"|---|---|",
        f"| **Target** | `{artifact.target}` |",
        f"| **Run ID** | `{artifact.run_id}` |",
        f"| **Generated** | {artifact.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')} |",
        f"| **Recon artifact** | `{artifact.recon_artifact_id}` |",
        "",
        "---",
        "",
        "## Summary",
        "",
        artifact.summary,
        "",
        "---",
        "",
        "## Actions",
        "",
    ]

    current_priority = None
    for i, action in enumerate(artifact.actions, 1):
        priority_key = action.priority.value if hasattr(action.priority, "value") else str(action.priority)
        label = _PRIORITY_LABEL.get(priority_key, priority_key.upper())

        if priority_key != current_priority:
            current_priority = priority_key
            lines += [f"### [{label}]", ""]

        obs = ", ".join(f"`{o}`" for o in action.observation_ids) if action.observation_ids else "—"
        lines += [
            f"#### {i}. {action.title}",
            "",
            f"**Category:** {action.category}  ",
            f"**Observations:** {obs}",
            "",
            action.description,
            "",
            f"**Rationale:** {action.rationale}",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


def render_retrieval_report(artifact: "RetrievalArtifact") -> str:
    """Render a RetrievalArtifact as a human-readable markdown report."""
    lines: list[str] = []

    lines += [
        "# Athena Retrieval Report",
        "",
        "| | |",
        "|---|---|",
        f"| **Target** | `{artifact.target}` |",
        f"| **Run ID** | `{artifact.run_id}` |",
        f"| **Generated** | {artifact.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')} |",
        f"| **Plan artifact** | `{artifact.plan_artifact_id}` |",
        "",
        "---",
        "",
        "## Summary",
        "",
        artifact.summary,
        "",
        "---",
        "",
        f"## Findings ({len(artifact.findings)})",
        "",
    ]

    for i, f in enumerate(artifact.findings, 1):
        input_str = json.dumps(f.tool_input, separators=(",", ":"))
        output_excerpt = f.tool_output[:500] + ("..." if len(f.tool_output) > 500 else "")
        action_ref = f"`{f.action_id}`" if f.action_id else "—"

        lines += [
            f"### {i}. {f.notes[:80]}{'...' if len(f.notes) > 80 else ''}",
            "",
            f"**Tool:** `{f.tool}`  ",
            f"**Input:** `{input_str}`  ",
            f"**Action:** {action_ref}  ",
            f"**Specialist:** `{f.specialist_id}`",
            "",
            "```",
            output_excerpt,
            "```",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


_RISK_LABEL = {
    "critical": "CRITICAL",
    "high":     "HIGH",
    "medium":   "MEDIUM",
    "low":      "LOW",
}


def render_report(artifact: "ReportArtifact") -> str:
    """Render a ReportArtifact as a final engagement report in markdown."""
    risk_key = artifact.risk_rating.value if hasattr(artifact.risk_rating, "value") else str(artifact.risk_rating)
    risk_label = _RISK_LABEL.get(risk_key, risk_key.upper())

    lines: list[str] = [
        f"# Athena Engagement Report — `{artifact.target}`",
        "",
        "| | |",
        "|---|---|",
        f"| **Risk Rating** | **{risk_label}** |",
        f"| **Run ID** | `{artifact.run_id}` |",
        f"| **Generated** | {artifact.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')} |",
        f"| **Retrieval artifact** | `{artifact.retrieval_artifact_id}` |",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        artifact.executive_summary,
        "",
        "---",
        "",
    ]

    for section in artifact.sections:
        lines += [
            f"## {section.title}",
            "",
            section.content,
            "",
            "---",
            "",
        ]

    lines += [
        "## Recommendations",
        "",
    ]
    for i, rec in enumerate(artifact.recommendations, 1):
        lines.append(f"{i}. {rec}")
    lines += ["", "---", "", "*Generated by Athena*"]

    return "\n".join(lines)


class RunLogger:
    def __init__(self, run_id: str, artifacts_dir: Path) -> None:
        self._run_dir = artifacts_dir / run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger(f"athena.run.{run_id}")
        # File handler writes to run.log alongside the JSON artifacts.
        fh = logging.FileHandler(self._run_dir / "run.log")
        fh.setFormatter(UTC_FORMATTER)
        self._logger.addHandler(fh)
        # propagate=True (default) means messages also reach the athena stream handler.

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    def log(self, event: str) -> None:
        self._logger.info(event)

    def write_artifact(self, name: str, content: str) -> Path:
        """Write a JSON string to artifacts/<run_id>/<name>.json."""
        path = self._run_dir / f"{name}.json"
        path.write_text(content)
        return path
