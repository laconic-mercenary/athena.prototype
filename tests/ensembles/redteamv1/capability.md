# Capability — redteam-meridian

## What this ensemble does

Runs a structured, OSINT-led red team engagement. Given only a company's public **domain**,
it discovers the target through open-source intelligence, then walks the kill chain:
OSINT discovery → network recon → MITRE-mapped attack planning → exploitation → formal report.

The operator gives a domain and an objective — NOT a target IP. Recon discovers the actual
host itself. Exploitation runs primarily as **non-interactive RCE** (no reverse shell needed).

An operator-approval gate between planning and exploitation ensures no exploit traffic reaches
the target without the operator reviewing and approving the attack plan.

## briefing_required

```yaml
briefing_required:
  - name: domain
    type: string
    example: "meridian-www"
    description: >
      The target organisation's public domain. The engagement STARTS from OSINT against this
      domain — the ensemble discovers the actual host/IP itself. The operator's objective
      usually already contains the domain; extract it rather than re-asking.
  - name: scope
    type: string
    example: "Recon the public footprint; if a way in exists, reach sensitive customer data. Report business impact."
    description: >
      Engagement objective / scope. The operator's initial message normally states this
      already — do not re-ask if it is clear.
```

**Do NOT ask the operator for a target IP/address, an LHOST, or an LPORT.** Recon discovers the
target via OSINT, and the exploit committee uses non-interactive RCE, so there is no reverse-shell
callback to configure. If the operator's message names a domain and an objective, you have enough
to submit the plan.

Always declare an `operator_approval` gate after `planning` in the EngagementPlan. This is
mandatory — no exploit traffic reaches the target without operator sign-off.

## Committees

### recon
- **Input:** domain + scope (from the engagement brief).
- **Flow:** OSINT first — an OSINT specialist maps the public footprint (tech stack, and any
  exposed code repositories or infrastructure); a source-code intelligence specialist inspects
  any repository it finds for secrets in commit history (internal hosts, credentials, config); a
  Dark Web analyst checks breach/paste exposure in parallel. If surface dark-web sources are clean
  but deeper (paywalled) tiers remain, the leader asks the operator whether to dig further. Recon
  then scans and enumerates whatever target it establishes.
- **Output:** `ReconOutput` — the discovered target + OSINT provenance, open ports with
  service/version, web paths, CVE candidates, an attack-surface summary and ATT&CK hypotheses
  (authored by the recon leader).
- **Adequate when:** an ORIGIN host (not the public/fronting domain or its CDN edge) was
  discovered from OSINT and confirmed reachable with at least one open port and either CVE
  candidates or a surface assessment.
- **Retry if:** OSINT yields no repository/host, OR the only candidate target is the public/
  fronting domain behind a CDN (re-run the OSINT hop to recover the true origin host, or
  ask_operator), OR nmap returns no open ports on the discovered origin (retry with a slower scan).

### planning
- **Consumes:** `recon` (required — full ReconOutput).
- **Output:** `PlanOutput` — ordered attack vectors with MITRE technique IDs, CVE references,
  success criteria, and a full kill-chain sequence.
- **Mode:** Compare — three `exploit_planner` specialists from three model families run in
  parallel (Claude Haiku; Foundation-Sec; Kimi-K3 on a Modal endpoint). Leader selects the most
  technically credible plan via `select_result`, then a `mitre_mapper` specialist supplies the
  authoritative ATT&CK technique mapping and kill chain for the selected plan.
- **Adequate when:** at least one exploit vector with a realistic path to initial access.
- **Gate after:** `operator_approval` — operator reviews and approves before exploit traffic.

### exploit
- **Consumes:** `planning` (required — full PlanOutput); `recon` (optional).
- **Output:** `ExploitOutput` — code-execution status, user achieved, techniques confirmed,
  data harvested, and vector-level outcomes.
- **Elements:** an application-exploitation specialist matched to the target's web stack (prefers
  non-interactive RCE, with an interactive-shell fallback); a datastore specialist, activated only
  if an internal datastore is discovered; and an interactive-shell fallback operator. The leader
  matches specialists to the technology it encounters and prefers non-interactive RCE.
- **Operator interaction:** the exploit leader calls `ask_operator` before sensitive operations —
  privilege escalation, reaching an internal datastore, or reading credentials / sensitive data.
- **Adequate when:** objectives achieved or all planned vectors exhausted and the outcome reported.

### reporting
- **Consumes:** `exploit` (required); `recon` and `planning` (optional via `read_artifact`).
- **Elements:** `report_writer` drafts the narrative (executive summary, data exfiltrated,
  findings, remediation); a `mitre_mapper` specialist compiles the authoritative confirmed-
  technique list in parallel, so the writer is not carrying the ATT&CK mapping load.
- **Output:** `ReportOutput` — executive summary, data exfiltrated, confirmed ATT&CK techniques,
  markdown findings, and remediation recommendations.
- **Adequate when:** all confirmed techniques are mapped and remediation covers the primary path.

## Operator gates

| After | Type | Redo available |
|-------|------|----------------|
| `planning` | operator_approval | yes (iterate) |

Declare exactly this gate in the EngagementPlan. Additional gates (e.g. after `recon` or
`exploit`) may be added at operator discretion during briefing.

## Ask the operator if
- OSINT surfaces no exposed repository or host, or no origin host is recoverable (do not invent an IP).
- The nmap scan of the discovered target times out or returns 0 ports — confirm connectivity.
- Privilege escalation is available but requires destructive actions.
- An internal datastore or unexpected host is discovered (pivot / data-access opportunity).

## Dependencies
- `nmap` — installed on the harness machine
- `httpx` — HTTP client used by the HTTP and source-code-intelligence skills
- `pwntools` — for the interactive-shell fallback only
- Foundation-Sec — configured via `provider: ollama` in the manifest (planning committee only)
- Outbound internet from the harness — GitHub API access for `github_commits` OSINT skill
