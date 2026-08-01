# Recon Committee Playbook

## Element inventory

| Element | What it does | Skill | Step |
|---------|-------------|-------|------|
| `port_scan` | nmap service/version scan | `nmap_scan` | Step 1 |
| `web_enum` | HTTP path enumeration | `web_enum` | Step 1 |
| `cve_lookup` | ExploitDB search for discovered services | `searchsploit` | Step 2 |
| `threat_analyst` | Foundation-Sec ATT&CK surface assessment | none (reasoning) | Step 3 |

## Standard three-step sequence

**Step 1** — Submit `port_scan` and `web_enum` as two tasks in one step.
- Port scan brief: include target IP. Start with ports "1-1000"; expand to full range
  only if something unusual is suspected (e.g. service hinting at a high port).
- Web enum brief: use `http://<target>` initially. If HTTPS is open, enumerate that too.
  If no web port is visible yet, use port 80 speculatively — web_enum will fail gracefully.

**Step 2** — Submit `cve_lookup` as one task.
- Write the brief listing each significant service and version found in Step 1.
  Format each as `<service> <version>` on a separate line.
- Prioritise: web framework versions > SSH versions > FTP/other.

**Step 3** — Submit `threat_analyst` as one task.
- Write a structured brief containing:
  1. Full port listing (port/service/version)
  2. Web paths found (path + status code)
  3. CVE candidates from Step 2
- Foundation-Sec will produce ATT&CK technique hypotheses and a priority attack path.

## Adequacy

The ReconOutput is adequate when:
- At least one open port is confirmed.
- CVE candidates are populated, OR threat_analyst produced a surface assessment.
- `mitre_hypotheses` contains at least one technique ID.

## Escalation criteria (ask_operator)

- nmap returns 0 open ports (host unreachable, VPN problem, or wrong IP).
- nmap binary not found on the harness machine.
- Both web_enum and port_scan return connection errors (VPN down?).
