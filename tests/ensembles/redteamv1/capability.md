# Capability — redteam-htb

## What this ensemble does

Performs a structured red team engagement against a Linux target: network reconnaissance →
MITRE-mapped attack planning → exploitation via reverse shell → formal report.
Foundation-Sec provides ATT&CK analysis in both recon and planning.

An operator-approval gate between planning and exploitation ensures no exploit traffic
reaches the target without the operator reviewing and approving the attack plan.

## briefing_required

```yaml
briefing_required:
  - name: target
    type: string
    example: "10.10.11.5"
    description: >
      Hostname or IP address of the target. On Docker-based engagements this is
      typically a service name (e.g. "target"); on VPN-based engagements it is
      the machine's IP (e.g. "10.10.11.5").
  - name: lhost
    type: string
    example: "10.10.14.5"
    description: >
      Address the target will call back to for the reverse shell — either the
      harness machine's VPN interface IP (e.g. tun0) or a Docker service name
      resolvable from the target container (e.g. "athena_web").
  - name: lport
    type: integer
    example: 4444
    description: Port to listen on for the reverse shell callback. Must be free.
  - name: scope
    type: string
    example: "Full compromise — demonstrate impact and collect evidence of access"
    description: Engagement objective and scope constraints.
```

Always declare an `operator_approval` gate after `planning` in the EngagementPlan.
This is mandatory — no exploit traffic reaches the target without operator sign-off.

## Committees

### recon
- **Input:** target, lhost, scope (from engagement brief).
- **Output:** `ReconOutput` — open ports with service/version, web paths, CVE candidates,
  Foundation-Sec ATT&CK hypotheses, and attack surface summary.
- **Adequate when:** at least one open port found and either CVE candidates are identified
  or Foundation-Sec has produced a surface assessment with technique hypotheses.
- **Retry if:** nmap returned no open ports (possible timeout — retry with slower scan).

### planning
- **Consumes:** `recon` (required — full ReconOutput).
- **Output:** `PlanOutput` — ordered attack vectors with MITRE technique IDs, CVE
  references, success criteria, and a full kill-chain sequence.
- **Mode:** Compare — three `exploit_planner` specialists run in parallel (two Claude
  Haiku instances at different temperatures; one Foundation-Sec instance). Leader
  selects the most technically credible plan via `select_result`.
- **Adequate when:** at least one exploit vector is identified with a realistic path
  to initial shell access.
- **Gate after:** `operator_approval` — operator reviews the plan and approves before
  any exploit traffic is sent.

### exploit
- **Consumes:** `planning` (required — full PlanOutput); `recon` (optional).
- **Output:** `ExploitOutput` — shell status, user achieved, techniques confirmed,
  data harvested, and vector-level outcomes.
- **Elements:** `web_exploiter` (http_get, http_post, get_shell) and `shell_operator`
  (run_cmd, close_shell). Leader sequences them across multiple steps.
- **Operator interaction:** the exploit leader calls `ask_operator` before sensitive
  operations — privilege escalation, reading sensitive files, or pivoting to
  unexpected internal hosts.
- **Adequate when:** engagement objectives achieved or all planned vectors exhausted
  and the leader has reported the outcome.

### reporting
- **Consumes:** `exploit` (required); `recon` and `planning` (optional — read via
  `read_artifact` if the writer needs full context).
- **Output:** `ReportOutput` — executive summary, data exfiltrated, confirmed ATT&CK
  techniques, markdown findings, and remediation recommendations.
- **Adequate when:** all confirmed techniques are mapped and remediation covers the
  primary exploit path.

## Operator gates

| After | Type | Redo available |
|-------|------|----------------|
| `planning` | operator_approval | yes (iterate) |

The orchestrator should declare exactly this gate in the EngagementPlan. Additional
gates (e.g. after `exploit`) may be added at operator discretion during briefing.

## Ask the operator if
- The nmap scan times out or returns 0 ports — confirm the target address and connectivity.
- The reverse shell does not connect within the timeout — confirm lhost/lport and
  whether the target can make outbound TCP connections.
- Privilege escalation is available but requires destructive actions.
- Unexpected hosts are discovered on the internal network (pivot opportunity).

## Dependencies
- `nmap` — installed on the harness machine
- `pwntools` — installed in the Python environment (`pip install -e ".[redteam]"`)
- `httpx` — HTTP client used by http_get, http_post, get_shell (transitive via anthropic SDK)
- Foundation-Sec — configured via `provider: ollama` in the ensemble manifest
