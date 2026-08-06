# Red Team System Test v2 — OSINT-led Meridian Engagement

Design notes for the **v2** evolution of the Meridian Systems demo (`tests/system/redteam_easy/`).
Builds on `REDTEAM_SYSTEST.md` (v1) — read that first; this doc is the **delta**, not a rewrite.

Status: **design** (confirmed scope; not yet implemented)

---

## 1. Why v2

v1 works, but the operator hands the ensemble a bare target address, so the demo *reads* as
"hack this IP." v2 fixes the framing without rebuilding the vuln chain:

1. **OSINT-led discovery.** The operator gives a **name** (`meridian.openintel.to`) and asks
   Athena to "recon and see if any opportunities exist." Recon **discovers** the target the way
   a real team does — a leaky news page → a GitHub repo → a sandbox IP leaked in commit history.
   No elaborate engagement brief required; the engagement proceeds from a one-line objective.
2. **Technology-matched experts.** Leaders activate the right specialist as the stack is revealed:
   a **Flask/Python Exploitation Specialist** for the foothold, a **Redis Specialist** for the
   database. Same adaptive-orchestration beat, twice.
3. **Non-interactive RCE spine.** The exploit chain runs as discrete commands over the PyYAML RCE
   (one command per request, output read from the HTTP response) instead of a fragile reverse
   shell. This both reads cleanly on the graph and settles the shell-reliability problem.

The result is a story: **a domain name → an exposed sandbox → a customer-data breach.**

---

## 2. Engagement input (minimal briefing)

The operator provides only:

| Parameter | Value | Notes |
|-----------|-------|-------|
| objective | *"Recon `meridian.openintel.to` and report whether any opportunities to reach sensitive data exist."* | One line. No target IP, no attack plan. |

The orchestrator turns this into a recon-first plan; the operator approves proceeding to
exploitation at the gate **after** recon surfaces the opportunity. This showcases autonomy +
the operator gate, and removes the "operator already knows the answer" feel of v1.

**Open point:** the orchestrator must accept a domain/scope with no IP. Confirm the briefing
prompt no longer requires `target`/`lhost`/`lport` up front (lhost/lport only matter if we keep
the interactive-shell fallback; the non-interactive spine needs neither).

---

## 3. External OSINT surface (operator-hosted)

Two sources: a **public marketing site** and a **public GitHub repo**. All content is static and
seeded — nothing is generated at runtime. Note the marketing site is a *different* host from the
`target` sandbox: the site is Meridian's legit public presence; the sandbox is the internal box
leaked in git.

### 3.1 `meridian.openintel.to` — new `meridian_web` container
- A **new, separate container** in the compose serving simple static pages (nginx or a trivial
  static server). Exposes a host port; the operator points a **load balancer / tunnel** at it so
  the public domain resolves to that container. The recon agent reaches it over the internet via
  `http_get` (athena_web already has outbound on `external-net`).
- **`/`** — landing page: company blurb + a **clear link to `/news`**.
- **`/news`** — a puff piece, *"Meridian migrates its config service to Python/Flask"* (establishes
  the stack without spoiling the CVE) + a **clear link to the GitHub repo**.
- Keep it deliberately simple with obvious anchor links so the OSINT Specialist reliably follows
  landing → `/news` → repo.

### 3.2 GitHub repo (public, on the operator's own account)
Carries the leak in **commit history**, the classic "secret deleted but still in git":

- **Commit 1** adds a staging config file (e.g. `config/staging.env`) containing the **static
  sandbox IP** (§5).
- **Commit 2** deletes/scrubs that file — so the IP is gone from `HEAD` but recoverable from the
  historical commit.

The GitHub specialist recovers it via the public **GitHub API** (`/repos/{owner}/{repo}/commits`,
unauthenticated, 60 req/hr — ample), listing commits and fetching the blob at commit 1.

**Design decision (confirmed):** the git leak exposes the **sandbox IP only** — *not* the Redis
password. The Redis credential stays behind privesc (`/root/.redis_password`, v1), keeping the
RCE → privesc → loot → pivot chain causally necessary.

---

## 4. Recon committee (v2)

Prepend an **OSINT phase** as two distinct workers; the existing recon steps then run on the
*discovered* target. The two OSINT workers are separate elements (separate nodes on the graph),
run in sequence because GitHub depends on the URL the web scrape recovers.

### 4.1 New element: `web_osint` — **OSINT Specialist** (runs first)
- `http_get` the landing page → follow the **clear link to `/news`** → `http_get` `/news` →
  extract the **GitHub repo URL** + record the Flask/Werkzeug stack context from the article.
- (Naming: "OSINT Specialist" per operator; "Web Recon Specialist" is the alternative if we want
  to disambiguate from the GitHub worker, which is also technically OSINT.)

### 4.2 New element: `github_recon` — **GitHub Specialist** (its own worker)
- Input: the repo URL from §4.1. `github_commits(repo)` → walk history → recover the **static IP**
  from the commit-1 blob despite the commit-2 deletion.

### 4.3 Existing recon, now on the discovered IP
`os_check → port_scan → web_enum → cve_lookup`, targeting the recovered static IP — confirming
Flask/Werkzeug, `/debug`, and PyYAML 3.13 (CVE-2017-18342).

**`threat_analyst` removed.** The Foundation-Sec-8B (Ollama) threat-analyst element is dropped
from recon — it is slow and the recon leader (Claude) already synthesizes the
`attack_surface_summary` + `mitre_hypotheses` at `finish()` from the collected findings. (Removes
Foundation-Sec/Ollama from recon entirely; it still runs in the planning committee's `planner_fs`.)

### 4.4 `ReconOutput` deltas
- `discovered_target: str` — the IP recovered from OSINT (feeds every downstream step).
- `osint_sources: list[str]` — provenance (e.g. `meridian.openintel.to/news`, the repo URL,
  `commit <sha>`), so the report can show *how* the target was found.
- The leader now authors `attack_surface_summary` + `mitre_hypotheses` directly (previously from
  `threat_analyst`).

### 4.5 New skill: `github_commits`
- Input: repo (`owner/name` or URL). Calls the GitHub REST API for the commit list and fetches a
  commit's file blob. Returns commit metadata + the recovered file contents.
- Pure `httpx` + stdlib → travels in the ensemble, live via the bind mount, no new baked deps.
- Granted only to the GitHub Specialist (§4.2). `http_get` (granted to the OSINT Specialist)
  covers the website; the GitHub API is the only genuinely new skill.

---

## 5. Infrastructure changes

- **New `meridian_web` container** — serves the static public site (§3.1); exposes a host port
  that the operator's **load balancer / tunnel** maps to `meridian.openintel.to`. Separate from
  `target`; only needs to be reachable from the internet (for `http_get` to resolve the domain).
- **Static IP for `target`** on `engagement-net` (e.g. `10.10.20.30`) via compose — so the value
  the GitHub commit leaks is stable across runs and reads like a real internal IP. **Choose this
  before authoring the repo content.**
- `athena_web` needs **outbound internet** (already has `external-net`) to reach
  `meridian.openintel.to` and `api.github.com`.
- `db-net` segmentation (Redis reachable only from `target`) unchanged from v1.

---

## 6. Exploit committee (v2)

### 6.1 Flask/Python Exploitation Specialist (replaces `web_exploiter`)
Owns initial access and privesc, run **non-interactively**:
- Crafts PyYAML deserialization payloads (`!!python/object/apply:subprocess.check_output`) and
  delivers them via **`http_post` to `/api/parse-config`**, reading command output from the JSON
  response (`{"config": "..."}`). One command per request — no shell required.
- Confirms RCE (`id` → `www-data`), enumerates, then escalates: the SUID `python3.10` runs with
  euid root, so a single RCE call reads `/root/.redis_password` (and can drop a root shell if we
  want to *show* privesc as a distinct beat).
- Interactive `get_shell`/`run_cmd` kept only as a fallback, not the spine.

*Note:* for this single Flask target we **replace** the generic `web_exploiter` rather than run
both — a generalist has nothing else to triage here. Coexistence (generalist triages → specialist
goes deep) is a later multi-target scaling story.

### 6.2 Redis Specialist (activated on discovery)
- The exploit leader tasks it **once Redis is discovered** on `db-net` (from the app's config,
  `netstat`, or connection attempts surfaced during enumeration) — mirroring how the Flask
  specialist was matched to the web stack.
- Redis is reachable only from `target`, and `target` has no `redis-cli`, so the specialist's
  expertise is a **Python RESP one-liner delivered through the Flask specialist's RCE channel**:
  connect to `redis:6379`, `AUTH` with the privesc-recovered password, `KEYS *` → `GET` each.
- Exfiltrates `customer:*` (10 PII records) + `session:*` (admin tokens) + `meta:*` → this is the
  climax, populating `ExploitOutput.data_harvested`.

---

## 7. The narrative arc (the money shot)

> Operator gives a **name** → recon reads a leaky news page → pivots to a **GitHub repo** →
> recovers a **sandbox IP** deleted from HEAD but alive in history → confirms a **Flask/PyYAML**
> stack → the **Flask specialist** lands non-interactive RCE and escalates to root → recovers the
> DB credential → the **Redis specialist activates on discovery** and opens the segmented customer
> database → report leads with the **breach impact**.

That is a red-team engagement, not a port scan.

---

## 8. Change summary

| Area | Change | Live via bind mount? |
|------|--------|----------------------|
| Recon | New `web_osint` element — **OSINT Specialist** (scrapes the site) | ✅ |
| Recon | New `github_recon` element — **GitHub Specialist**, its own worker | ✅ |
| Recon | **Remove `threat_analyst`** (Foundation-Sec); leader synthesizes the summary/MITRE | ✅ |
| Recon | `ReconOutput`: `discovered_target`, `osint_sources` | ✅ |
| Skills | New `github_commits` (GitHub API) | ✅ |
| Exploit | Replace `web_exploiter` with Flask/Python Exploitation Specialist | ✅ |
| Exploit | Add Redis Specialist, leader-activated on Redis discovery | ✅ |
| Exploit | Bias the whole committee to non-interactive RCE (`http_post` + `check_output`) | ✅ |
| Infra | New `meridian_web` container + operator load balancer → `meridian.openintel.to` | Operator-side |
| Infra | Static IP for `target`; author the public GitHub repo content | Operator-side |

No core-harness rebuild is required for §3–§6 — it's ensemble + infra.

---

## 9. Out of scope for this doc (related, deferred)

- **Structured multiple-choice questions** (radio picker for Leader/Orchestrator `ask_operator` /
  `ask_user`, Claude-Code-style) — a core Python + SSE + UI change; tracked separately.
- **MITRE ATT&CK Expert** planning element (maps the chosen vector to tactics/techniques) — a
  clean future add to the planning committee; not required for the v2 flow above.
