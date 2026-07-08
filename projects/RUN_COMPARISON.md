# Run 1 vs Run 2 — Comparison

| | Run 1 (`f49baafb`) | Run 2 (`4743b378`) |
|-|--------------------|--------------------|
| Date | 2026-07-06 04:10 UTC | 2026-07-06 06:31 UTC |
| Total time | 13m 38s | 11m 20s |
| Risk rating | CRITICAL | CRITICAL |

---

## Timing

| Committee | Run 1 | Run 2 | Δ |
|-----------|-------|-------|---|
| Recon | 7m 16s | 6m 02s | −1m 14s |
| Planning | 1m 52s | 1m 57s | +5s |
| Retrieval | 1m 36s | 1m 28s | −8s |
| Reporting | 1m 54s | 1m 53s | −1s |
| **Total** | **13m 38s** | **11m 20s** | **−2m 18s** |

Run 2 was faster primarily because recon produced fewer observations (less token generation) and retrieval ran fewer postgres queries.

---

## Recon committee

| Metric | Run 1 | Run 2 | Δ |
|--------|-------|-------|---|
| Total observations | 66 | 34 | −32 |
| signal_warn | 15 | 9 | −6 |
| signal_info | 10 | 9 | −1 |
| noise | 41 | 16 | −25 |
| Specialists registered | 7 | 6 | −1 |
| Phase 3 operators summoned | 3 (service, web, network) | 2 (web, network) | −1 |

### Consistency — critical findings

Both runs independently identified every critical finding from scratch:

| Finding | Run 1 | Run 2 |
|---------|-------|-------|
| credentials.json exposed | ✅ | ✅ |
| db_admin:Sup3rS3cr3t!2024 | ✅ | ✅ |
| pgdatabase:5432 lateral movement target | ✅ | ✅ |
| ik_prod_a1b2c3d4e5f6 API key | ✅ | ✅ |
| Apache mod_status unauthenticated | ✅ | ✅ |
| Apache directory listing on /files/ | ✅ | ✅ |
| robots.txt /files/ disclosure | ✅ | ✅ |
| No HTTPS | ✅ | ✅ |

**The critical finding set is fully reproducible across runs.**

### Differences in recon depth

Run 1's leader was more aggressive in Phase 3 — it re-summoned all three operator types and re-confirmed every critical finding with full body retrieval, yielding many duplicate confirmations. This contributed to the larger observation count but also greater redundancy. Run 2's leader was more selective — it re-summoned web and network operators but not service, and produced a more compact artifact without sacrificing any of the critical findings.

The 41 `noise` observations in Run 1 vs 16 in Run 2 reflects Run 1's broader port sweep (service_operator probed ~15 additional closed ports in Phase 3).

### Threat analyst comparison

| | Run 1 | Run 2 |
|-|-------|-------|
| CVE output | `CVE-2024-XXXXXX` placeholder | `(no CVEs identified)` — honest |
| Risk indicators | Accurate | Accurate |
| Format compliance | Mostly clean | Code blocks in recommended actions (format violation) |
| Influenced leader | Minimally — leader reasoned independently | Minimally — leader reasoned independently |

Run 2's "(no CVEs identified)" is the more accurate and useful output — the model correctly declined to fabricate a CVE ID. Run 1's placeholder created a false signal. Both runs show the leader is capable of independently identifying CWEs and CVE candidates (CVE-2023-38408 in Run 1), so the analyst's CVE accuracy matters less than its risk indicator and follow-up quality.

The code-block format violation in Run 2's recommended actions (`bash` fences with shell commands) is a persistent issue — the model follows the section headers correctly but occasionally breaks the "no code blocks" instruction within sections.

---

## Planning committee

| Metric | Run 1 | Run 2 |
|--------|-------|-------|
| Total actions | 14 | 12 |
| Critical | 4 | 5 |
| High | 6 | 4 |
| Medium | 4 | 3 |

### Shared actions (semantically equivalent)

| Theme | Run 1 | Run 2 |
|-------|-------|-------|
| SSH credential reuse | ✅ (critical) | ✅ (critical) |
| PostgreSQL lateral movement | ✅ (critical) | ✅ (critical) |
| Remove credentials.json | ✅ (critical) | ✅ (critical) |
| Restrict mod_status | ✅ **high** | ✅ **critical** ← elevated |
| API key endpoint discovery | ✅ (critical) | ✅ (high) |
| Employee portal login discovery | ✅ (high) | ✅ (high) |
| Apache version header suppression | ✅ (medium) | ✅ (high) ← elevated |
| Remove robots.txt /files/ disclosure | ✅ (medium) | ✅ (medium) |
| SSH auth method enumeration | ✅ (high) | ✅ (medium) ← downgraded |
| Rotate all credentials | embedded in remediation action | ✅ explicit standalone (high) |

### Actions only in Run 1

- **Deep enumerate /files/ for additional secrets** — wordlist probe for .bak, .env, id_rsa, etc.
- **Assess CVE-2023-38408 SSH agent forwarding** — explicit CVE check for OpenSSH 8.9p1
- **Audit Apache enabled modules** (`apache2ctl -M`) — module baseline
- **Map full Docker network topology** — 172.18.0.0/24 enumeration from within the container

### Actions only in Run 2

- **Audit logs for prior credential access** (critical) — forensic review of Apache access logs since 2026-07-01 to establish exposure window; Run 1 mentioned this in the report but didn't plan it as an explicit action
- **Cleartext HTTP credential interception assessment** (medium) — novel framing around HTTP-in-transit risk, not just the file exposure
- **Rotate all exposed credentials** as an explicit standalone action rather than embedded in a remediation item

### Priority calibration differences

Run 2 treated mod_status restriction as **critical** (Run 1: high). The reasoning is sound — mod_status leaks internal IPs and live request URIs that directly aid lateral movement planning, making it operationally as urgent as the credential exposure. This is a legitimate interpretation difference, not an error.

---

## Retrieval committee

| Metric | Run 1 | Run 2 | Δ |
|--------|-------|-------|---|
| Total findings | 34 | 27 | −7 |
| http_head | 18 | 5 | −13 |
| http_get | 5 | 15 | +10 |
| extract_links | 2 | 1 | −1 |
| postgres_query | 9 | 6 | −3 |

### Postgres query comparison

| Query | Run 1 | Run 2 |
|-------|-------|-------|
| Database enumeration | ✅ | ✅ |
| User privilege check (usesuper, usecreatedb) | ✅ | ❌ not run |
| Table enumeration | ✅ | ✅ |
| employees table | ✅ | ✅ |
| api_keys table | ✅ | ✅ |
| system_config table | ✅ | ✅ |
| pg_read_file() privilege check | ✅ | ❌ not run |
| pg_read_file('/etc/hostname') execution | ✅ | ❌ not run |
| version() | ✅ | ✅ |

**Key gap in Run 2:** The db_specialist did not test `pg_read_file()` capability. Run 1 confirmed `db_admin` can read arbitrary files from the pgdatabase host filesystem — a significant escalation finding that extends the blast radius beyond the database itself. This was missed entirely in Run 2.

### Exfiltrated data

Both runs exfiltrated identical data from the three database tables. The content is stable — same credentials, same employee records, same system secrets. The gap is purely in the depth of privilege assessment.

### Web retriever approach

Run 2 favoured `http_get` (15 calls) over `http_head` (5 calls) compared to Run 1's inverse preference. Both approaches covered the same endpoint surface. Run 2 was slightly more thorough in confirming response bodies but didn't probe any endpoint category that Run 1 missed.

---

## Reporting committee

| Metric | Run 1 | Run 2 |
|--------|-------|-------|
| Risk rating | CRITICAL | CRITICAL |
| Recommendations | 15 | 13 |
| Sections | 4 | 4 |

### Section structure comparison

| Run 1 | Run 2 |
|-------|-------|
| Technical Findings | Technical Findings |
| Risk Assessment | Risk Assessment |
| Vulnerability Chain Summary | Scope of Compromise and Blast Radius |
| Unremediated Exposure Status | **Findings Summary Table** ← novel |

Run 2 replaced the narrative vulnerability chain with a structured **Findings Summary Table** (severity / finding / status / location). This is more scannable and a better format for an executive audience. Run 1's "Unremediated Exposure Status" section was operationally valuable — it explicitly called out that every misconfiguration was still live at the time of retrieval. Run 2 distributed this information throughout the recommendations instead.

### Recommendation quality

Run 2 introduced **time-bounded recommendations** (within 1 hour / 4 hours / 8 hours / 24 hours / 48 hours / 1 week) — a significant improvement over Run 1's IMMEDIATE / HIGH / MEDIUM labels. This is more actionable for an incident response team.

Run 2 also added recommendations not present in Run 1:
- **Deploy TLS** — explicit HTTPS enforcement within 4 hours (Run 1 mentioned it as medium)
- **Container-wide secrets audit** — scan all containers on 172.18.0.0/16 for similar exposures
- **Centralised log aggregation + alerting** — operational monitoring recommendation
- **Security awareness training** — process recommendation

Run 1 included recommendations not in Run 2:
- **Audit pg_read_file() and COPY privileges** — direct consequence of the capability test Run 2 didn't run
- **Locate the employee portal login** (explicit recommendation)
- **Full Apache module audit** (apache2ctl -M)

---

## Open questions — status

These were flagged as unresolved at the end of Run 1:

| Question | Run 2 status |
|----------|-------------|
| SSH password auth confirmed? | Still unresolved — planned (medium) but not executed in retrieval |
| Employee portal login located? | Still unresolved — planned (high) and probed, still 404 across all standard paths |
| API service for exposed keys? | Still unresolved — API endpoints not on target container |
| Full Docker network topology? | Still unresolved — not attempted by retrieval |
| CVE-2024-6387 regreSSHion patch status? | Still unresolved — not assessed |
| pgdatabase host filesystem (pg_read_file)? | **Regression** — Run 1 confirmed capability and read /etc/hostname; Run 2 did not attempt |

---

## Summary assessment

**What is consistent:** The critical finding set is fully reproducible. Both runs independently discovered credentials.json, correctly followed the robots.txt → /files/ → credentials.json chain, connected to pgdatabase, and exfiltrated identical data from all three tables. The pipeline is reliable on the core mission.

**Where Run 2 improved:** Faster (−2m 18s). More compact recon (34 vs 66 observations) without missing anything critical. More honest CVE assessment from the analyst. Time-bounded recommendations are more actionable. The Findings Summary Table section is a better report format. Mod_status elevated to critical is a reasonable calibration.

**Where Run 2 regressed:** The db_specialist did not test `pg_read_file()` — this was the single most significant new finding in Run 1 and was entirely absent from Run 2. Planning also dropped four actions present in Run 1 (file enumeration depth, CVE-2023-38408, Apache module audit, Docker network mapping).

**Foundation-Sec observation:** The threat analyst output continues to have format compliance issues (code blocks appearing in recommended actions). The CVE honesty improved. The analyst's risk indicators are accurate in both runs but have not yet influenced what the leader does in Phase 3 — the leader appears to reason about follow-up from the operator findings directly rather than being driven by the analyst's recommendations.
