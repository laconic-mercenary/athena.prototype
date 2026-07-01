"""Retrieval committee: Leader + two specialists with real tool access.

Specialists execute planned actions against the target using live tools
(HTTP fetches, SQL queries). Each specialist run produces a JSON array of
RetrievedFindings which Python collects directly. The leader only writes
the narrative summary — it does not re-list findings.

Artifact handoff: both PlanArtifact and ReconArtifact JSON are injected
into every specialist's initial message as context.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

import yaml

from athena.agent_loop import run_agent
from athena.config import AthenaConfig
from athena.model_backend import BackendFactory, ToolDefinition, make_backend
from athena.schemas import (
    PlanArtifact,
    ReconArtifact,
    RetrievalArtifact,
    RetrievedFinding,
    Specialist,
)
from athena.tools import (
    extract_links,
    http_get,
    http_head,
    postgres_query,
)
from athena.utils import extract_json

_log = logging.getLogger("athena.retrieval")


# ---------------------------------------------------------------------------
# Tool definitions (what the LLM sees)
# ---------------------------------------------------------------------------

_HTTP_GET = ToolDefinition(
    name="http_get",
    description="HTTP GET request. Returns status code, headers, and body (up to 64 KB).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to fetch (host must be 'target')"},
        },
        "required": ["url"],
    },
)

_HTTP_HEAD = ToolDefinition(
    name="http_head",
    description="HTTP HEAD request. Returns status code and headers, no body.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL"},
        },
        "required": ["url"],
    },
)

_EXTRACT_LINKS = ToolDefinition(
    name="extract_links",
    description="Parse HTML and return all unique hyperlinks resolved against a base URL.",
    parameters={
        "type": "object",
        "properties": {
            "html": {"type": "string", "description": "HTML content to parse"},
            "base_url": {"type": "string", "description": "Base URL for resolving relative links"},
        },
        "required": ["html", "base_url"],
    },
)

_POSTGRES_QUERY = ToolDefinition(
    name="postgres_query",
    description=(
        "Execute a read-only SQL query against the target PostgreSQL database. "
        "Host must be 'pgdatabase'. All queries run in a read-only transaction."
    ),
    parameters={
        "type": "object",
        "properties": {
            "host":     {"type": "string",  "description": "Database host (must be pgdatabase)"},
            "port":     {"type": "integer", "description": "Database port (typically 5432)"},
            "database": {"type": "string",  "description": "Database name"},
            "username": {"type": "string",  "description": "Database username"},
            "password": {"type": "string",  "description": "Database password"},
            "query":    {"type": "string",  "description": "SQL query to execute"},
        },
        "required": ["host", "port", "database", "username", "password", "query"],
    },
)

_SUMMON_SPECIALIST = ToolDefinition(
    name="summon_specialist",
    description="Summon a retrieval specialist. Returns their findings as a JSON array.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": ["web_retriever", "db_specialist"],
                "description": "Specialist to summon",
            },
        },
        "required": ["name"],
    },
)

_SPECIALIST_TOOLS: dict[str, list[ToolDefinition]] = {
    "web_retriever": [_HTTP_GET, _HTTP_HEAD, _EXTRACT_LINKS],
    "db_specialist": [_POSTGRES_QUERY],
}

_SPECIALIST_TITLES: dict[str, str] = {
    "web_retriever": "Web Retriever",
    "db_specialist": "Database Specialist",
}


# ---------------------------------------------------------------------------
# Tool result formatters
# ---------------------------------------------------------------------------

def _fmt_http_get(result) -> str:
    lines = [f"Summary: {result.summary}", f"Status: {result.status_code}", ""]
    for k, v in result.headers.items():
        lines.append(f"{k}: {v}")
    lines += ["", "Body (first 3000 chars):", result.body[:3000]]
    return "\n".join(lines)


def _fmt_http_head(result) -> str:
    lines = [f"Summary: {result.summary}", f"Status: {result.status_code}", ""]
    for k, v in result.headers.items():
        lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _fmt_extract_links(result) -> str:
    lines = [f"Summary: {result.summary}", ""]
    lines += [f"  {link}" for link in result.links]
    return "\n".join(lines)


def _fmt_postgres(result) -> str:
    if result.error:
        return f"Query failed: {result.error}"
    lines = [f"Summary: {result.summary}", f"Query: {result.query}", ""]
    if result.columns:
        lines.append("Columns: " + " | ".join(result.columns))
        for row in result.rows:
            lines.append("  " + " | ".join(str(v) for v in row))
    else:
        lines.append("(no rows returned)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-specialist dispatch
# ---------------------------------------------------------------------------

def _make_dispatch(name: str) -> Callable[[str, dict], str]:
    def dispatch(tool: str, inp: dict) -> str:
        try:
            if tool == "http_get":
                return _fmt_http_get(http_get(inp["url"]))
            if tool == "http_head":
                return _fmt_http_head(http_head(inp["url"]))
            if tool == "extract_links":
                return _fmt_extract_links(extract_links(inp["html"], inp["base_url"]))
            if tool == "postgres_query":
                return _fmt_postgres(postgres_query(
                    host=inp["host"],
                    port=inp["port"],
                    database=inp["database"],
                    username=inp["username"],
                    password=inp["password"],
                    query=inp["query"],
                ))
            return f"Error: tool '{tool}' is not available to {name}"
        except Exception as exc:
            return f"Error running {tool}: {exc}"
    return dispatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_system(config_path: Path) -> str:
    raw = yaml.safe_load(config_path.read_text())
    if "system" not in raw:
        raise ValueError(f"Agent config {config_path} missing 'system' field")
    return raw["system"]


def _resolve(local: Optional[str], committee: Optional[str], global_: str) -> str:
    return local or committee or global_


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_retrieval_committee(
    plan_artifact: PlanArtifact,
    recon_artifact: ReconArtifact,
    config: AthenaConfig,
    _backend_factory: BackendFactory = make_backend,
) -> RetrievalArtifact:
    """Run the Retrieval committee and return a validated RetrievalArtifact."""
    retrieval_cfg = config.committees["retrieval"]
    global_model = config.model.default
    global_provider = config.model.provider
    ollama_url = config.model.ollama_base_url

    spec_by_name = {
        Path(s.config_path).stem: s for s in retrieval_cfg.specialists
    }

    # Serialise both upstream artifacts once; injected into every specialist.
    plan_json = plan_artifact.model_dump_json(indent=2)
    recon_json = recon_artifact.model_dump_json(indent=2)

    # Python collects all findings from specialist runs directly.
    all_findings: list[RetrievedFinding] = []

    def _run_specialist(name: str) -> str:
        if name not in spec_by_name:
            return json.dumps({"error": f"Unknown specialist: {name!r}"})
        if name not in _SPECIALIST_TOOLS:
            return json.dumps({"error": f"No tool set defined for: {name!r}"})

        spec_cfg = spec_by_name[name]
        model = _resolve(spec_cfg.model, retrieval_cfg.model, global_model)
        provider = _resolve(spec_cfg.provider, retrieval_cfg.provider, global_provider)

        specialist = Specialist(title=_SPECIALIST_TITLES[name])

        _log.info("summoning %s", name)
        system = _load_system(spec_cfg.config_path)
        backend = _backend_factory(provider, ollama_url)

        initial = (
            f"Target: {plan_artifact.target}\n"
            f"Your specialist ID: {specialist.id}\n\n"
            f"PlanArtifact:\n{plan_json}\n\n"
            f"ReconArtifact:\n{recon_json}\n\n"
            "Execute the actions in your domain. "
            "Output ONLY the JSON array of findings when done."
        )

        raw = run_agent(
            agent_id=f"athena.retrieval.{name}",
            system=system,
            initial_message=initial,
            tools=_SPECIALIST_TOOLS[name],
            tool_dispatch=_make_dispatch(name),
            backend=backend,
            model=model,
            max_iterations=config.max_agent_iterations,
        )

        try:
            items = extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            return json.dumps({"error": f"Invalid JSON from {name}: {exc}", "raw": raw[:400]})

        findings = [
            RetrievedFinding(
                specialist_id=specialist.id,
                action_id=item.get("action_id", ""),
                tool=item.get("tool", ""),
                tool_input=item.get("tool_input", {}),
                tool_output=item.get("tool_output", ""),
                notes=item.get("notes", ""),
            )
            for item in items
        ]
        all_findings.extend(findings)
        _log.info("%s complete — %d finding(s)", name, len(findings))
        return json.dumps([f.model_dump() for f in findings])

    # --- Leader ---
    leader_cfg = retrieval_cfg.leader
    leader_model = _resolve(leader_cfg.model, retrieval_cfg.model, global_model)
    leader_provider = _resolve(leader_cfg.provider, retrieval_cfg.provider, global_provider)

    leader = Specialist(title="Retrieval Leader")
    leader_system = _load_system(leader_cfg.config_path)
    leader_backend = _backend_factory(leader_provider, ollama_url)

    def leader_dispatch(tool: str, inp: dict) -> str:
        if tool == "summon_specialist":
            return _run_specialist(inp["name"])
        return f"Unknown tool: {tool!r}"

    leader_initial = (
        f"Target: {plan_artifact.target}\n"
        f"Your specialist ID: {leader.id}\n\n"
        f"PlanArtifact:\n{plan_json}\n\n"
        f"ReconArtifact:\n{recon_json}\n\n"
        "Begin the retrieval committee workflow."
    )

    _log.info("leader coordinating retrieval")
    raw_summary = run_agent(
        agent_id="athena.retrieval.leader",
        system=leader_system,
        initial_message=leader_initial,
        tools=[_SUMMON_SPECIALIST],
        tool_dispatch=leader_dispatch,
        backend=leader_backend,
        model=leader_model,
        max_iterations=config.max_agent_iterations,
        max_tokens=8192,
    )

    summary_data = extract_json(raw_summary)

    return RetrievalArtifact(
        run_id=plan_artifact.run_id,
        target=plan_artifact.target,
        plan_artifact_id=plan_artifact.artifact_id,
        findings=all_findings,
        summary=summary_data["summary"],
    )
