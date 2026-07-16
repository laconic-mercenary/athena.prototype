"""Recon committee: Operators (Claude) + Threat Analyst (Foundation-Sec) + Leader (Claude).

Flow:
  Phase 1 — Python runs all three operators directly. Operators are Claude agents
             with scoped tools; they return raw findings.
  Phase 2 — Python passes all operator findings to the Foundation-Sec threat analyst.
             The analyst reasons over findings and returns threat intelligence (no tools).
  Phase 3 — Leader (Claude) receives findings + threat analysis. Can use
             summon_operator(name, task) for targeted follow-up based on analyst
             recommendations.
  Phase 4 — Leader calls record_observation() once per finding to classify and emit
             real-time agent.finding events, then outputs only {"summary": "..."}.
"""

from __future__ import annotations

import json
import logging
import queue
from pathlib import Path
from typing import Callable, Optional

import yaml
from pubsub import pub

from athena.agent_loop import SYNTHESIS_MAX_TOKENS, run_agent
from athena.config import AthenaConfig
from athena.model_backend import (
    BackendFactory,
    ToolDefinition,
    make_backend,
)
from athena.schemas import (
    Observation,
    OrchestratorApproval,
    RawFinding,
    ReconArtifact,
    Specialist,
    ThreatAnalysis,
)
from athena.tools import (
    check_port,
    extract_links,
    http_get,
    http_head,
    nmap_scan,
    ssh_banner,
    tcp_banner,
    tls_probe,
)
from athena.utils import extract_json

_log = logging.getLogger("athena.recon")

_COMMITTEE = "recon"

# The leader records one observation per finding in a single agent loop (Phase 4),
# so its iteration count scales with the number of findings, not reasoning depth.
# A large recon run (web path enumeration alone yields ~9 findings, plus network,
# service, and any Phase 3 follow-up) can exhaust the normal 20-iteration cap before
# the leader emits its summary. This budget is sized with wide headroom over the
# realistic worst-case finding count so the loop always reaches the summary turn.
_LEADER_MAX_ITERATIONS = 100


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_NMAP_SCAN = ToolDefinition(
    name="nmap_scan",
    description="TCP connect scan against the target. Returns open ports with service and version info.",
    parameters={
        "type": "object",
        "properties": {"host": {"type": "string", "description": "Target hostname"}},
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
    description="HTTP GET request. Returns status code, headers, and body.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Full URL to fetch"}},
        "required": ["url"],
    },
)

_HTTP_HEAD = ToolDefinition(
    name="http_head",
    description="HTTP HEAD request. Returns status code and headers, no body.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Full URL"}},
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

_TCP_BANNER = ToolDefinition(
    name="tcp_banner",
    description="Connect to a TCP port and read any banner the service sends.",
    parameters={
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Target hostname"},
            "port": {"type": "integer", "description": "TCP port number"},
        },
        "required": ["host", "port"],
    },
)

_TLS_PROBE = ToolDefinition(
    name="tls_probe",
    description="Probe TLS/SSL on a port. Returns certificate info and cipher suites.",
    parameters={
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Target hostname"},
            "port": {"type": "integer", "description": "Port number"},
        },
        "required": ["host", "port"],
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

_SUMMON_OPERATOR = ToolDefinition(
    name="summon_operator",
    description="Summon an operator to gather intelligence on the target.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": ["network_operator", "service_operator", "web_operator"],
                "description": "Which operator to summon",
            },
            "task": {
                "type": "string",
                "description": "Specific instructions for the operator",
            },
        },
        "required": ["name", "task"],
    },
)

_RECORD_OBSERVATION = ToolDefinition(
    name="record_observation",
    description=(
        "Classify and record a single finding. Call once per finding — do not batch. "
        "Each call is immediately surfaced to the operator."
    ),
    parameters={
        "type": "object",
        "properties": {
            "specialist_id": {"type": "string", "description": "ID of the specialist who collected this finding"},
            "command": {"type": "string", "description": "Command or request that produced this finding"},
            "command_output": {"type": "string", "description": "Output of that command"},
            "classification": {
                "type": "string",
                "enum": ["signal_critical", "signal_warn", "signal_info", "noise", "unknown"],
                "description": "Severity classification",
            },
            "category": {
                "type": "string",
                "enum": ["network", "service", "configuration", "exposure", "authentication"],
                "description": "Finding category",
            },
            "comments": {
                "type": "array",
                "description": "Classification rationale; must include CVE or specific secret for warn/critical",
                "items": {
                    "type": "object",
                    "properties": {
                        "author_id": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["author_id", "text"],
                },
            },
        },
        "required": [
            "specialist_id", "command", "command_output",
            "classification", "category", "comments",
        ],
    },
)

_OPERATOR_TOOLS: dict[str, list[ToolDefinition]] = {
    "network_operator": [_NMAP_SCAN, _CHECK_PORT],
    "service_operator": [_SSH_BANNER, _TCP_BANNER, _TLS_PROBE],
    "web_operator":     [_HTTP_GET, _HTTP_HEAD, _EXTRACT_LINKS],
}

_OPERATOR_TITLES: dict[str, str] = {
    "network_operator": "Port Scanner",
    "service_operator": "Banner Probe",
    "web_operator":     "Web Crawler",
}

_DEFAULT_TASKS: dict[str, str] = {
    "network_operator": "Perform a full port scan and verify key service ports on the target.",
    "service_operator": "Grab banners from all open service ports. Probe TLS where applicable.",
    "web_operator":     "Crawl the target web application and enumerate all accessible endpoints.",
}


# ---------------------------------------------------------------------------
# Tool result formatters
# ---------------------------------------------------------------------------

def _fmt_nmap(result) -> str:
    lines = [f"Summary: {result.summary}", ""]
    if result.open_ports:
        lines.append("Open ports:")
        for p in result.open_ports:
            lines.append(f"  {p.port}/{p.protocol}  {p.service or '?'}  {p.version}")
    else:
        lines.append("No open ports found.")
    lines += ["", "Raw output:", result.raw_output]
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


def _fmt_tcp_banner(result) -> str:
    if result.error:
        return f"TCP banner failed: {result.error}"
    return f"Summary: {result.summary}\n\nBanner: {result.banner}"


def _fmt_tls_probe(result) -> str:
    if result.error:
        return f"TLS probe failed: {result.error}"
    return result.summary


def _fmt_extract_links(result) -> str:
    lines = [f"Summary: {result.summary}", ""]
    lines += [f"  {link}" for link in result.links]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Input summary helpers (for agent.tool_called events)
# ---------------------------------------------------------------------------

def _operator_input_summary(tool: str, inp: dict) -> str:
    if tool in ("nmap_scan",):
        return inp.get("host", "")
    if tool in ("check_port", "ssh_banner", "tcp_banner", "tls_probe"):
        return f"{inp.get('host', '')}:{inp.get('port', '')}"
    if tool in ("http_get", "http_head"):
        return inp.get("url", "")
    if tool == "extract_links":
        return inp.get("base_url", "")
    return str(inp)[:80]


def _leader_input_summary(tool: str, inp: dict) -> str:
    if tool == "summon_operator":
        return inp.get("name", "")
    if tool == "record_observation":
        return f"{inp.get('classification', '?')}: {inp.get('command', '')[:60]}"
    return str(inp)[:80]


# ---------------------------------------------------------------------------
# Per-operator dispatch (with tool_called events)
# ---------------------------------------------------------------------------

def _make_dispatch(name: str, run_id: str, agent_id: str) -> Callable[[str, dict], str]:
    def dispatch(tool: str, inp: dict) -> str:
        pub.sendMessage(
            "agent.tool_called",
            run_id=run_id,
            committee=_COMMITTEE,
            agent_id=agent_id,
            tool=tool,
            input_summary=_operator_input_summary(tool, inp),
        )
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
            if tool == "tcp_banner":
                return _fmt_tcp_banner(tcp_banner(inp["host"], inp["port"]))
            if tool == "tls_probe":
                return _fmt_tls_probe(tls_probe(inp["host"], inp["port"]))
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


def _format_for_analyst(findings_by_operator: dict[str, list[RawFinding]]) -> str:
    lines: list[str] = []
    for op_name, findings in findings_by_operator.items():
        title = _OPERATOR_TITLES.get(op_name, op_name)
        lines.append(f"[{title}]")
        if not findings:
            lines.append("  (no findings)")
        for f in findings:
            out = f.command_output[:500] + "…" if len(f.command_output) > 500 else f.command_output
            lines.append(f"  {f.command}")
            lines.append(f"  → {out}")
            if f.notes:
                lines.append(f"  note: {f.notes}")
        lines.append("")
    return "\n".join(lines)


def _format_leader_context(
    approval: OrchestratorApproval,
    findings_by_operator: dict[str, list[RawFinding]],
    threat_analysis: ThreatAnalysis,
) -> str:
    lines = [
        f"Target: {approval.target}",
        f"Run ID: {approval.run_id}",
        f"Engagement notes: {approval.notes}",
        "",
        "━━━ Phase 1: Operator Findings ━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for op_name, findings in findings_by_operator.items():
        title = _OPERATOR_TITLES.get(op_name, op_name)
        lines.append(f"[{title}]")
        for f in findings:
            out = f.command_output[:500] + "…" if len(f.command_output) > 500 else f.command_output
            lines.append(f"  {f.command}: {out}")
        if not findings:
            lines.append("  (no findings)")
        lines.append("")

    lines += ["━━━ Threat Analyst Report ━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append(threat_analysis.summary)
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "Use summon_operator for any recommended follow-up.",
        "Then call record_observation once per finding, and output the summary JSON.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_recon_committee(
    approval: OrchestratorApproval,
    config: AthenaConfig,
    _backend_factory: BackendFactory = make_backend,
    leader_queue: queue.Queue | None = None,
) -> ReconArtifact:
    """Run the Recon committee and return a validated ReconArtifact."""
    recon_cfg = config.committees["recon"]
    global_model = config.model.default
    global_provider = config.model.provider
    ollama_url = config.model.ollama_base_url
    run_id = approval.run_id

    spec_by_name = {Path(s.config_path).stem: s for s in recon_cfg.specialists}
    summoned: list[Specialist] = []

    def _run_operator(name: str, task: str) -> str:
        """Run an operator agent loop. Returns findings as a JSON string."""
        if name not in spec_by_name:
            return json.dumps({"error": f"Unknown operator: {name!r}"})
        if name not in _OPERATOR_TOOLS:
            return json.dumps({"error": f"No tool set for operator: {name!r}"})

        spec_cfg = spec_by_name[name]
        model = _resolve(spec_cfg.model, recon_cfg.model, global_model)
        provider = _resolve(spec_cfg.provider, recon_cfg.provider, global_provider)

        operator = Specialist(title=_OPERATOR_TITLES[name])
        summoned.append(operator)
        agent_id = f"athena.recon.{name}"

        _log.info("running operator %s", name)
        system = _load_system(spec_cfg.config_path)
        backend = _backend_factory(provider, ollama_url)

        pub.sendMessage(
            "agent.spawned",
            run_id=run_id,
            committee=_COMMITTEE,
            agent_id=agent_id,
            title=_OPERATOR_TITLES[name],
        )

        initial = (
            f"Target: {approval.target}\n"
            f"Task: {task}\n"
            f"Your operator ID: {operator.id}\n\n"
            "Perform your assigned task. Output ONLY the JSON array when done."
        )

        raw = run_agent(
            agent_id=agent_id,
            system=system,
            initial_message=initial,
            tools=_OPERATOR_TOOLS[name],
            tool_dispatch=_make_dispatch(name, run_id, agent_id),
            backend=backend,
            model=model,
            max_iterations=config.max_agent_iterations,
        )

        pub.sendMessage("agent.spun_down", run_id=run_id, committee=_COMMITTEE, agent_id=agent_id)

        try:
            items = extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            return json.dumps({"error": f"Invalid JSON from {name}: {exc}", "raw": raw[:400]})

        findings = [
            RawFinding(
                specialist_id=operator.id,
                command=item.get("command", ""),
                command_output=item.get("command_output", ""),
                notes=item.get("notes", ""),
            )
            for item in (items if isinstance(items, list) else [])
        ]
        _log.info("%s — %d finding(s)", name, len(findings))
        return json.dumps([f.model_dump() for f in findings])

    # --- Phase 1: Run all operators ---
    findings_by_operator: dict[str, list[RawFinding]] = {}
    for op_name, default_task in _DEFAULT_TASKS.items():
        raw_result = _run_operator(op_name, default_task)
        try:
            items = json.loads(raw_result)
            if isinstance(items, list):
                findings_by_operator[op_name] = [RawFinding(**item) for item in items]
            else:
                findings_by_operator[op_name] = []
        except Exception as exc:
            _log.warning("Phase 1 parse error for %s: %s", op_name, exc)
            findings_by_operator[op_name] = []

    # --- Phase 2: Threat analysis ---
    threat_analysis: ThreatAnalysis
    if "threat_analyst" not in spec_by_name:
        _log.warning("No threat_analyst configured — skipping threat analysis")
        threat_analysis = ThreatAnalysis(summary="No threat analyst configured.")
    else:
        analyst_cfg = spec_by_name["threat_analyst"]
        analyst_model = _resolve(analyst_cfg.model, recon_cfg.model, global_model)
        analyst_provider = _resolve(analyst_cfg.provider, recon_cfg.provider, global_provider)
        analyst_system = _load_system(analyst_cfg.config_path)
        analyst_backend = _backend_factory(analyst_provider, ollama_url)
        analyst_agent_id = "athena.recon.threat_analyst"
        analyst = Specialist(title="Signal Analyst")
        summoned.append(analyst)

        findings_text = _format_for_analyst(findings_by_operator)
        analyst_initial = (
            f"Target: {approval.target}\n\n"
            "Operator Findings\n"
            "─────────────────\n"
            f"{findings_text}"
        )

        _log.info("running threat analyst")
        pub.sendMessage(
            "agent.spawned",
            run_id=run_id,
            committee=_COMMITTEE,
            agent_id=analyst_agent_id,
            title="Signal Analyst",
        )
        pub.sendMessage(
            "agent.tool_called",
            run_id=run_id,
            committee=_COMMITTEE,
            agent_id=analyst_agent_id,
            tool="analyze_findings",
            input_summary="operator findings",
        )
        try:
            analyst_backend.begin(system=analyst_system, initial_message=analyst_initial)
            analyst_response = analyst_backend.complete(
                model=analyst_model, tools=None, max_tokens=4096
            )
            threat_analysis = ThreatAnalysis(summary=analyst_response.text or "")
        finally:
            pub.sendMessage(
                "agent.spun_down",
                run_id=run_id,
                committee=_COMMITTEE,
                agent_id=analyst_agent_id,
            )

    # --- Phase 3+4: Leader loop ---
    leader_cfg = recon_cfg.leader
    leader_model = _resolve(leader_cfg.model, recon_cfg.model, global_model)
    leader_provider = _resolve(leader_cfg.provider, recon_cfg.provider, global_provider)
    leader_agent_id = "athena.recon.leader"

    leader = Specialist(title="Recon Lead")
    leader_system = _load_system(leader_cfg.config_path)
    leader_backend = _backend_factory(leader_provider, ollama_url)

    # Observations are collected here as the leader calls record_observation.
    collected_observations: list[Observation] = []

    def leader_dispatch(tool: str, inp: dict) -> str:
        pub.sendMessage(
            "agent.tool_called",
            run_id=run_id,
            committee=_COMMITTEE,
            agent_id=leader_agent_id,
            tool=tool,
            input_summary=_leader_input_summary(tool, inp),
        )

        if tool == "summon_operator":
            return _run_operator(
                inp["name"],
                inp.get("task", "Follow up on analyst recommendations."),
            )

        if tool == "record_observation":
            try:
                obs = Observation(**inp)
            except Exception as exc:
                return f"Error recording observation: {exc}"
            collected_observations.append(obs)
            # Derive a human-readable summary for the finding event.
            comment_text = obs.comments[0].text if obs.comments else obs.command
            pub.sendMessage(
                "agent.finding",
                run_id=run_id,
                committee=_COMMITTEE,
                agent_id=leader_agent_id,
                classification=obs.classification.value,
                summary=comment_text,
            )
            return "Observation recorded."

        return f"Unknown tool: {tool!r}"

    leader_initial = _format_leader_context(approval, findings_by_operator, threat_analysis)

    _log.info("leader synthesising artifact")
    pub.sendMessage(
        "agent.spawned",
        run_id=run_id,
        committee=_COMMITTEE,
        agent_id=leader_agent_id,
        title="Recon Lead",
    )

    raw_artifact = run_agent(
        agent_id=leader_agent_id,
        system=leader_system,
        initial_message=leader_initial,
        tools=[_SUMMON_OPERATOR, _RECORD_OBSERVATION],
        tool_dispatch=leader_dispatch,
        backend=leader_backend,
        model=leader_model,
        max_iterations=_LEADER_MAX_ITERATIONS,
        max_tokens=SYNTHESIS_MAX_TOKENS,
        operator_queue=leader_queue,
    )

    pub.sendMessage("agent.spun_down", run_id=run_id, committee=_COMMITTEE, agent_id=leader_agent_id)

    artifact_data = extract_json(raw_artifact)

    return ReconArtifact(
        run_id=approval.run_id,
        target=approval.target,
        specialists=[leader] + summoned,
        observations=collected_observations,
        summary=artifact_data["summary"],
        threat_analysis=threat_analysis,
    )
