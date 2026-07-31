# Capability — redteam-htb

## What this ensemble does
Performs a structured red team engagement against an HTB-style Linux target: network
reconnaissance → MITRE-mapped attack planning → exploitation via reverse shell →
formal report. Foundation-Sec provides ATT&CK analysis in both recon and planning.

The engagement ends with shell access and flag capture (`user.txt` / `root.txt`).
An operator-approval gate between planning and exploitation ensures no exploit traffic
reaches the target without the operator reviewing and approving the attack plan.

## briefing_required

```yaml
briefing_required:
  - name: target
    type: string
    example: "10.10.11.5"
    description: IP address of the HTB target machine.
  - name: lhost
    type: string
    example: "10.10.14.5"
    description: >
      Harness machine's VPN interface IP (tun0) — the address the target will call
      back to for the reverse shell. Run `ip addr show tun0` to confirm.
  - name: lport
    type: integer
    example: 4444
    description: Port to listen on for the reverse shell callback. Must be free.
  - name: scope
    type: string
    example: "Full compromise — user.txt and root.txt"
    description: Engagement objective and scope constraints.
```

Always declare an `operator_approval` gate after `planning` in the EngagementPlan.
This is mandatory — no exploit traffic reaches the target without operator sign-off.

## Committees

### recon
- **Input:** target IP, scope (from engagement brief).
- **Output:** `ReconOutput` — open ports with service/version, web paths, CVE candidates,
  Foundation-Sec ATT&CK hypotheses, and attack surface summary.
- **Steps:** Step 1 — port_scan + web_enum (run in sequence); Step 2 — cve_lookup
  (uses service versions from step 1); Step 3 — threat_analyst (Foundation-Sec synthesis).
- **Adequate when:** at least one open port found, CVE candidates identified or
  Foundation-Sec has produced a surface assessment.
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
- **Output:** `ExploitOutput` — shell status, user achieved, flags found, techniques
  confirmed, vector-level outcomes.
- **Elements:** `web_exploiter` (http_get, http_post, get_shell) and `shell_operator`
  (run_cmd, close_shell). Leader sequences them across multiple steps.
- **Operator interaction:** the exploit leader calls `ask_operator` before sensitive
  operations — privilege escalation, reading flags, or pivoting to unexpected hosts.
- **Adequate when:** shell obtained and at least one flag captured, OR all planned
  vectors exhausted and the leader has reported the outcome.

### reporting
- **Consumes:** `exploit` (required); `recon` and `planning` (optional — read via
  `read_artifact` if the writer needs full context).
- **Output:** `ReportOutput` — executive summary, flags, confirmed ATT&CK techniques,
  markdown findings, and remediation recommendations.
- **Adequate when:** all confirmed techniques are mapped, flags are listed, and
  remediation covers the primary exploit path.

## Operator gates

| After | Type | Redo available |
|-------|------|----------------|
| `planning` | operator_approval | yes (iterate) |

The orchestrator should declare exactly this gate in the EngagementPlan. Additional
gates (e.g. after `exploit`) may be added at operator discretion during briefing.

## Ask the operator if
- The nmap scan times out or returns 0 ports — confirm the target IP and VPN connection.
- The reverse shell does not connect within the timeout — confirm lhost/lport and
  whether the target's firewall allows outbound TCP.
- Privilege escalation is available and requires destructive actions.
- Unexpected hosts are discovered on the internal network (pivot opportunity).

## Dependencies
- `nmap` — installed on the harness machine (`apt install nmap`)
- `pwntools` — installed in the Python environment (`pip install pwntools`)
- `requests` — standard; used by web_enum, http_get, http_post, get_shell
- Foundation-Sec — live on Modal, configured via `provider: ollama` in `athena.yml`
