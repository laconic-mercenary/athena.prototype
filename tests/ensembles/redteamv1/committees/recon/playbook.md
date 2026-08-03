# Recon Committee Playbook

## Element inventory

| Element | What it does | Skill |
|---------|-------------|-------|
| `port_scan` | nmap service/version scan | `nmap_scan` |
| `web_enum` | HTTP path enumeration | `web_enum` |
| `cve_lookup` | ExploitDB search for discovered services | `searchsploit` |
| `threat_analyst` | Foundation-Sec ATT&CK surface assessment | none (reasoning) |

## Adequacy

The ReconOutput is adequate when:
- At least one open port is confirmed.
- CVE candidates are populated, OR threat_analyst produced a surface assessment.
- `mitre_hypotheses` contains at least one technique ID.

## Escalation criteria (ask_operator)

- nmap returns 0 open ports (host unreachable or wrong IP).
- nmap binary not found on the harness machine.
- Both web_enum and port_scan return connection errors.
