"""Recon committee: Leader + four specialists.

The Leader is an LLM agent with one tool — summon_specialist(name). It calls
specialists reactively based on what each one finds, then classifies all
findings and emits the ReconArtifact.

Specialists are isolated agent loops with scoped tools. They output a JSON
array of RawFindings and are never asked to classify.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

import yaml

from athena.agent_loop import run_agent
from athena.config import AthenaConfig
from athena.model_backend import (
    BackendFactory,
    ModelBackend,
    ToolDefinition,
    make_backend,
)
from athena.schemas import (
    Observation,
    OrchestratorApproval,
    RawFinding,
    ReconArtifact,
    Specialist,
)
from athena.tools import (
    check_port,
    extract_links,
    http_get,
    http_head,
    nmap_scan,
    ssh_banner,
)
from athena.utils import extract_json

_log = logging.getLogger("athena.recon")


# ---------------------------------------------------------------------------
# Tool definitions (what the LLM sees)
# ---------------------------------------------------------------------------

_NMAP_SCAN = ToolDefinition(
    name="nmap_scan",
    description=(
        "TCP connect scan against the target. Port scope is hardcoded — you cannot"
        " specify which ports. Returns open ports with service and version info."
    ),
    parameters={
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Target hostname"},
        },
        "required": ["host"],
    },
)

_CHECK_PORT = ToolDefinition(
    name="check_port",
    description="Check whether a specific TCP port is open on the target.",
    parameters={
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Target hostname"},
            "port": {"type": "integer", "description": "TCP port number"},
        },
        "required": ["host", "port"],
    },
)

_HTTP_GET = ToolDefinition(
    name="http_get",
    description="HTTP GET request. Returns status code, headers, and body (up to 64 KB).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to fetch"},
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

_SSH_BANNER = ToolDefinition(
    name="ssh_banner",
    description="Connect to an SSH port and read the server identification banner.",
    parameters={
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Target hostname"},
            "port": {"type": "integer", "description": "SSH port (typically 22)"},
        },
        "required": ["host", "port"],
    },
)

_EXTRACT_LINKS = ToolDefinition(
    name="extract_links",
    description=(
        "Parse HTML and return all unique hyperlinks resolved against a base URL."
    ),
    parameters={
        "type": "object",
        "properties": {
            "html": {"type": "string", "description": "HTML content to parse"},
            "base_url": {"type": "string", "description": "Base URL for resolving relative links"},
        },
        "required": ["html", "base_url"],
    },
)

_SUMMON_SPECIALIST = ToolDefinition(
    name="summon_specialist",
    description=(
        "Summon a specialist agent. Returns their raw findings as a JSON array."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": ["network_scout", "ssh_expert", "rest_expert", "apache_expert"],
                "description": "Specialist to summon",
            },
        },
        "required": ["name"],
    },
)

# Which tools each specialist can use
_SPECIALIST_TOOLS: dict[str, list[ToolDefinition]] = {
    "network_scout": [_NMAP_SCAN, _CHECK_PORT],
    "ssh_expert":    [_SSH_BANNER],
    "rest_expert":   [_HTTP_GET, _HTTP_HEAD, _EXTRACT_LINKS],
    "apache_expert": [_HTTP_GET, _HTTP_HEAD],
}

_SPECIALIST_TITLES: dict[str, str] = {
    "network_scout": "Network Scout",
    "ssh_expert":    "SSH Expert",
    "rest_expert":   "REST Expert",
    "apache_expert": "Apache Expert",
}


# ---------------------------------------------------------------------------
# Tool result formatters — convert typed results to strings the LLM reads
# ---------------------------------------------------------------------------

def _fmt_nmap(result) -> str:
    lines = [f"Summary: {result.summary}", ""]
    if result.open_ports:
        lines.append("Open ports:")
        for p in result.open_ports:
            lines.append(f"  {p.port}/{p.protocol}  {p.service or '?'}  {p.version}")
    else:
        lines.append("No open ports found in scanned range.")
    lines += ["", "Raw nmap output:", result.raw_output]
    return "\n".join(lines)


def _fmt_port_check(result) -> str:
    return result.summary


def _fmt_http_get(result) -> str:
    lines = [f"Summary: {result.summary}", "", f"Status: {result.status_code}"]
    for k, v in result.headers.items():
        lines.append(f"{k}: {v}")
    lines += ["", "Body (first 3000 chars):", result.body[:3000]]
    return "\n".join(lines)


def _fmt_http_head(result) -> str:
    lines = [f"Summary: {result.summary}", "", f"Status: {result.status_code}"]
    for k, v in result.headers.items():
        lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _fmt_ssh_banner(result) -> str:
    if result.error:
        return f"SSH banner failed: {result.error}"
    return f"Summary: {result.summary}\n\nBanner: {result.banner}"


def _fmt_extract_links(result) -> str:
    lines = [f"Summary: {result.summary}", ""]
    lines += [f"  {link}" for link in result.links]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-specialist dispatch tables
# ---------------------------------------------------------------------------

def _make_dispatch(name: str) -> Callable[[str, dict], str]:
    """Return a tool dispatch function for the named specialist."""
    def dispatch(tool: str, inp: dict) -> str:
        try:
            if tool == "nmap_scan":
                return _fmt_nmap(nmap_scan(inp["host"]))
            if tool == "check_port":
                return _fmt_port_check(check_port(inp["host"], inp["port"]))
            if tool == "http_get":
                return _fmt_http_get(http_get(inp["url"]))
            if tool == "http_head":
                return _fmt_http_head(http_head(inp["url"]))
            if tool == "ssh_banner":
                return _fmt_ssh_banner(ssh_banner(inp["host"], inp["port"]))
            if tool == "extract_links":
                return _fmt_extract_links(extract_links(inp["html"], inp["base_url"]))
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

def run_recon_committee(
    approval: OrchestratorApproval,
    config: AthenaConfig,
    _backend_factory: BackendFactory = make_backend,
) -> ReconArtifact:
    """Run the Recon committee and return a validated ReconArtifact."""
    recon_cfg = config.committees["recon"]
    global_model = config.model.default
    global_provider = config.model.provider
    ollama_url = config.model.ollama_base_url

    # Build lookup: stem of config filename → SpecialistConfig
    spec_by_name = {
        Path(s.config_path).stem: s for s in recon_cfg.specialists
    }

    # Registry of all Specialist identities created during this run
    summoned: list[Specialist] = []

    def _run_specialist(name: str) -> str:
        """Runs a specialist agent loop; returns their findings as a JSON string."""
        if name not in spec_by_name:
            return json.dumps({"error": f"Unknown specialist: {name!r}"})
        if name not in _SPECIALIST_TOOLS:
            return json.dumps({"error": f"No tool set defined for: {name!r}"})

        spec_cfg = spec_by_name[name]
        model = _resolve(spec_cfg.model, recon_cfg.model, global_model)
        provider = _resolve(spec_cfg.provider, recon_cfg.provider, global_provider)

        specialist = Specialist(title=_SPECIALIST_TITLES[name])
        summoned.append(specialist)

        _log.info("summoning %s", name)
        system = _load_system(spec_cfg.config_path)
        backend = _backend_factory(provider, ollama_url)

        initial = (
            f"Target: {approval.target}\n"
            f"Your specialist ID: {specialist.id}\n\n"
            "Perform your assigned recon tasks. Output ONLY the JSON array when done."
        )

        raw = run_agent(
            agent_id=f"athena.recon.{name}",
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

        # Enforce correct specialist_id — don't trust the LLM to copy it accurately
        findings = [
            RawFinding(
                specialist_id=specialist.id,
                command=item.get("command", ""),
                command_output=item.get("command_output", ""),
                notes=item.get("notes", ""),
            )
            for item in items
        ]
        _log.info("%s complete — %d finding(s)", name, len(findings))
        return json.dumps([f.model_dump() for f in findings])

    # --- Leader ---
    leader_cfg = recon_cfg.leader
    leader_model = _resolve(leader_cfg.model, recon_cfg.model, global_model)
    leader_provider = _resolve(leader_cfg.provider, recon_cfg.provider, global_provider)

    leader = Specialist(title="Recon Leader")
    leader_system = _load_system(leader_cfg.config_path)
    leader_backend = _backend_factory(leader_provider, ollama_url)

    def leader_dispatch(tool: str, inp: dict) -> str:
        if tool == "summon_specialist":
            return _run_specialist(inp["name"])
        return f"Unknown tool: {tool!r}"

    leader_initial = (
        f"Target: {approval.target}\n"
        f"Run ID: {approval.run_id}\n"
        f"Your specialist ID: {leader.id}\n"
        f"Engagement notes: {approval.notes}\n\n"
        "Begin the recon committee workflow."
    )

    _log.info("leader synthesising artifact")
    raw_artifact = run_agent(
        agent_id="athena.recon.leader",
        system=leader_system,
        initial_message=leader_initial,
        tools=[_SUMMON_SPECIALIST],
        tool_dispatch=leader_dispatch,
        backend=leader_backend,
        model=leader_model,
        max_iterations=config.max_agent_iterations,
        max_tokens=8192,
    )

    artifact_data = extract_json(raw_artifact)

    return ReconArtifact(
        run_id=approval.run_id,
        target=approval.target,
        specialists=[leader] + summoned,
        observations=[Observation(**obs) for obs in artifact_data["observations"]],
        summary=artifact_data["summary"],
    )
