# 03 — Demo Scenario: Meridian Systems (technical walkthrough)

*The point: the operator gives **only a domain**. The ensemble discovers the real target itself via
OSINT, then walks the kill chain to the crown jewels (customer PII in Redis). Fully sandboxed,
intentionally vulnerable, authorized.*

## Premise
- Operator input: `meridian.openintel.to` + an objective (recon the footprint; if a way in exists,
  reach sensitive data; report business impact). **No IP, no LHOST/LPORT.**
- Meridian is a fictional company (the site is labelled *DEMONSTRATION ONLY*).

## Infrastructure (`tests/system/redteam_easy`, docker-compose)
- **meridian_web** (nginx :8002) — static marketing site (`/` → `/news`), fronted publicly as
  `meridian.openintel.to`. `/news` links to a **public GitHub repo** (`meridian-client-x`).
- **target** (Flask app, static IP **10.10.20.30** on `engagement-net`) — the real victim:
  - PyYAML unsafe `yaml.load` **RCE (CVE-2017-18342)** at `/api/parse-config`.
  - A **SUID `python3.10`** (privesc primitive).
  - Env `REDIS_HOST=redis` (visible post-RCE) and root-only `/root/.redis_password`.
- **redis** (segmented `db-net`, password `Meridian2024!`) — **10 customer PII records + admin
  session tokens**. Reachable **only from the target**, never from the harness.
- **The leak:** the sandbox IP `10.10.20.30` lives in the repo's **git history** — added in one
  commit, "scrubbed" in a later one, still recoverable.

## Kill chain, committee by committee

### 1. Recon — OSINT-led discovery
- **web_osint** — http_get the landing page, follow same-origin links to `/news`, extract the GitHub
  repo URL verbatim (budget raised so it can follow the link, not stop at the front page).
- **github_recon** — `repo_fetch` (orient: sees the `config/` dir, requirements) → `github_commits`
  (scan diffs) → recovers **`10.10.20.30:5000`** from the scrubbed commit. **This becomes the target.**
- **darkweb_recon** — 4 *separate* source lookups (paste / breach / forum / onion); all clean →
  the leader **asks the operator** "dig deeper or proceed with the GitHub lead?" (a human beat).
- **os_check** — unix_type_check / windows_smb_check / windows_rdp_check → Linux.
- **port_scan / web_enum / cve_lookup** — enumerate the discovered target: Werkzeug/Flask, PyYAML →
  CVE-2017-18342.
- **Output** `ReconOutput`: discovered target + OSINT provenance, open ports, CVE candidates,
  attack-surface summary, ATT&CK hypotheses.
- **Guard:** the public domain / CDN edge is **not** a valid target — recon must produce the origin
  IP or it's declared inadequate.

### 2. Planning — MITRE-mapped attack plan
- **Compare mode:** 3 analysts (Claude Haiku / Foundation-Sec / Kimi-K3 on Modal) produce competing
  plans; the leader `select_result`s the most credible.
- **mitre_mapper** then attaches authoritative ATT&CK technique IDs + the ordered kill chain.
- **Output** `PlanOutput`: ordered vectors, CVE refs, success criteria, MITRE chain.
- **→ `operator_approval` gate:** no exploit traffic reaches the target until the operator approves.

### 3. Exploit — non-interactive RCE
- **flask_exploiter** — non-interactive RCE via an http_post PyYAML payload:
  `!!python/object/apply:subprocess.check_output [["sh","-c","<cmd> 2>&1"]]` — the command's output
  comes back in the app's JSON response. Confirm with `id` (→ `www-data`).
- Enumerate: `uname`, SUID search (`find / -perm -4000`), `env` (→ discovers `REDIS_HOST=redis`).
- **Privesc** *(ask_operator first)* — the SUID `python3.10`, invoked directly, reads root-only
  `/root/.redis_password`.
- **redis_operator** *(ask_operator first)* — activated once Redis is discovered: runs a base64'd
  Python RESP one-liner **through the target's RCE** (the target has no redis-cli) to AUTH + `KEYS *`
  + dump all customer PII + session tokens. **This is the objective.**
- **shell_operator** — interactive-shell fallback (rarely needed; non-interactive is preferred).
- **Output** `ExploitOutput`: code-exec status, root achieved, data harvested, techniques confirmed.

### 4. Reporting
- **report_writer** drafts the narrative (exec summary, data exfiltrated, findings, remediation);
  **mitre_mapper** compiles the confirmed-technique ATT&CK table in parallel.
- **Output** `ReportOutput`: risk rating, exec summary, ATT&CK table, findings + remediation, business
  impact framing.

## Story beats to hit on stage
1. "We only handed it a **domain**" → recon reconstructs the target from a leaked git commit.
2. **Multi-source** recon: GitHub succeeds, dark web is clean → the operator decides whether to dig.
3. **Three model families** vote on the plan; a **MITRE specialist** standardizes the mapping.
4. Operator **approves** → non-interactive RCE → **SUID privesc** → **cross-network Redis** dump.
5. Every risky step **paused for operator sign-off**; **KILL SWITCH** always one click away.
