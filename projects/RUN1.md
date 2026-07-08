# Run 1 — Engagement Findings

**Run ID:** `f49baafb-5d2c-4889-a658-6d5e02763809`  
**Date:** 2026-07-06  
**Target:** `target` (Sarif Industries Internal Portal — `172.18.0.2`)  
**Duration:** 13 min 38 sec (04:10:46 → 04:23:24 UTC)  
**Overall risk rating:** CRITICAL  

---

## Pipeline timing

| Committee | Started | Completed | Duration |
|-----------|---------|-----------|----------|
| Recon | 04:10:46 | 04:18:02 | 7m 16s |
| Planning | 04:18:02 | 04:19:54 | 1m 52s |
| Retrieval | 04:19:54 | 04:21:30 | 1m 36s |
| Reporting | 04:21:30 | 04:23:24 | 1m 54s |

---

## Target profile

| Property | Value |
|----------|-------|
| IP address | 172.18.0.2 |
| Organisation | Sarif Industries |
| Application | Internal Employee Portal |
| Open ports | 22/tcp (SSH), 80/tcp (HTTP) |
| SSH service | OpenSSH 8.9p1 Ubuntu-3ubuntu0.15 |
| HTTP service | Apache httpd 2.4.52 (Ubuntu) |
| HTTPS | Not present — port 443 closed |
| Database | pgdatabase:5432 (separate container, internal network only) |

No other ports open across an extended check_port sweep (3306, 5432, 6379, 8080, 8443, 9200, 27017, 8888, 4000, 4443, 9000, 9090, 2375, 2376, 11211, 1433, 1521, 5000, 5001, 5601 — all closed).

---

## Recon committee

**Observations:** 66 total — 15 `signal_warn`, 10 `signal_info`, 41 `noise`

**Phases run:**
- Phase 1: network_operator, service_operator, web_operator (Claude, Python-driven)
- Phase 2: threat_analyst (Foundation-Sec-8B, bulleted markdown — first run with new format)
- Phase 3: leader (Claude Sonnet) — triggered follow-up via `summon_operator` on both service_operator and web_operator
- Phase 4: leader emitted ReconArtifact

**Specialists registered:** 7 (leader + 2× network_operator + 2× service_operator + 2× web_operator — Phase 3 re-summoned service and web operators)

### signal_warn findings

| Obs ID | Category | Command | Finding |
|--------|----------|---------|---------|
| `8688bb25` | configuration | http_head /robots.txt | robots.txt exists and `Disallow: /files/` directly advertises the sensitive path |
| `e4b89705` | configuration | http_head /server-status | Apache mod_status publicly accessible without authentication — HTTP 200 |
| `d7a5baf4` | exposure | http_head /files/ | Directory listing enabled on /files/ — HTTP 200, no auth (CWE-548) |
| `c48c5f6b` | configuration | http_get /robots.txt | Full body confirmed: `User-agent: * / Disallow: /files/` |
| `94bdc58d` | configuration | http_get /server-status | Live server internals exposed: internal IPs, worker PIDs, request URIs, load averages |
| `006ce5d0` | exposure | http_get /files/ | Directory index confirms `credentials.json` (221 bytes, 2026-07-01 13:10) |
| `6835f616` | authentication | http_get /files/credentials.json | **CRITICAL** — Plaintext production creds: `db_admin:Sup3rS3cr3t!2024`, `pgdatabase:5432`, API key `ik_prod_a1b2c3d4e5f6` |
| `a03f55c9` | exposure | extract_links /files/ | Directory index links directly enumerate `credentials.json` as a clickable hyperlink |
| `e0eca00d` | configuration | http_head /server-status (Phase 3) | Re-confirmed accessible, `Connection: close` noted |
| `d12ff595` | authentication | http_head /files/credentials.json (Phase 3) | Re-confirmed accessible: 200, `application/json`, 221 bytes |
| `03503b17` | configuration | http_get /server-status (Phase 3) | Full body: internal IP `172.18.0.4`, PIDs 25/26, live request URIs including recon activity, load 4.17/3.93/4.35 |
| `07686b8d` | configuration | http_get /robots.txt (Phase 3) | Re-confirmed |
| `9c27ae9c` | exposure | http_get /files/ (Phase 3) | Re-confirmed directory listing with single file |
| `f1f7a5f8` | authentication | http_get /files/credentials.json (Phase 3) | **CRITICAL** — Full body confirmed: `{environment: production, database: {host: pgdatabase, port: 5432, username: db_admin, password: Sup3rS3cr3t!2024}, api: {internal_key: ik_prod_a1b2c3d4e5f6}}` |
| `d7dfb77b` | exposure | extract_links /files/ (Phase 3) | Re-confirmed credentials.json hyperlink in directory listing |

### Credentials harvested by recon

| Secret | Value | Source |
|--------|-------|--------|
| PostgreSQL host | pgdatabase:5432 | credentials.json |
| PostgreSQL username | db_admin | credentials.json |
| PostgreSQL password | Sup3rS3cr3t!2024 | credentials.json |
| API key | ik_prod_a1b2c3d4e5f6 | credentials.json |

### CVEs / CWEs identified by recon leader

| Reference | Description | Observations |
|-----------|-------------|--------------|
| CWE-548 | Information Exposure Through Directory Listing | d7a5baf4, 006ce5d0, 9c27ae9c, a03f55c9 |
| CWE-312 | Cleartext Storage of Sensitive Information | 6835f616, f1f7a5f8 |
| CWE-256 | Plaintext Storage of Password | 6835f616, f1f7a5f8 |
| CWE-497 | Exposure of System Data to Unauthorized Control Sphere | e4b89705, 94bdc58d, 03503b17 |
| CWE-16 | Configuration (mod_status default config) | e4b89705 |
| CVE-2023-38408 | SSH agent forwarding RCE — flagged as monitoring concern for OpenSSH 8.9p1 | 4a703dc4 |

### Threat analyst output (Foundation-Sec — first bulleted-format run)

Output arrived in the correct four-section structure after the `</think>` reasoning block:

```
### CVE Candidates
- CVE-2024-XXXXXX — Apache HTTPD 2.4.52 server-status endpoint (placeholder)

### Risk Indicators
- Exposed credentials.json in /files/ (db credentials + API key)
- Accessible Apache server-status revealing system metrics
- Potentially outdated OpenSSH 8.9p1 and Apache 2.4.52

### Recommended Follow-up
- Service Operator: verify SSH configuration, restrict remote login
- Web Operator: disable server-status, audit remaining endpoints, check /admin and /api

### Assessment
Critical exposure of production credentials and internal system diagnostics...
```

**Assessment:** Format is working — bulleted sections land cleanly. CVE was a placeholder (model could not commit to a specific ID without patch-level data). Risk indicators and follow-up recommendations were accurate. The recon leader independently identified CVE-2023-38408 and the CWE references from its own reasoning, independent of the analyst output.

### Recon leader summary

> The target (Sarif Industries internal portal at 172.18.0.2) presents a minimal two-port attack surface (SSH/22, HTTP/80), but contains critical web-layer exposures that represent an immediate threat. Most severely, a production credentials file at http://target/files/credentials.json is publicly accessible without authentication, disclosing plaintext PostgreSQL credentials (db_admin:Sup3rS3cr3t!2024 targeting host pgdatabase:5432) and an internal API key (ik_prod_a1b2c3d4e5f6) — constituting CWE-312 and CWE-256 violations that enable direct lateral movement within the 172.18.0.x Docker network. The exposed database credentials reference an internal Docker network host, making them directly usable for lateral movement. Additionally, OpenSSH 8.9p1 (Ubuntu suffix 3ubuntu0.15) on port 22 requires urgent verification against CVE-2024-6387 ('regreSSHion').

---

## Planning committee

**Actions generated:** 14

| Priority | ID | Title | Category |
|----------|----|-------|----------|
| Critical | `10e115ed` | SSH credential reuse test | credential_access |
| Critical | `d6f48140` | Lateral movement to pgdatabase host | credential_access |
| Critical | `093c454c` | Test API key against internal services | credential_access |
| Critical | `b4671adb` | Remediate credentials.json public exposure | configuration_audit |
| High | `9c5146c6` | Disable Apache directory listing on /files/ | configuration_audit |
| High | `d03741db` | Restrict mod_status to localhost only | configuration_audit |
| High | `825ad8eb` | Enumerate SSH authentication methods | service_exploit |
| High | `3bce2610` | Deep enumerate /files/ for additional secrets | web_enumeration |
| High | `99fe04cf` | Enumerate employee portal login endpoint | web_enumeration |
| High | `bc4212e4` | Assess CVE-2023-38408 SSH agent forwarding | service_exploit |
| Medium | `1694ea6f` | Remove sensitive path from robots.txt | configuration_audit |
| Medium | `99139d51` | Harden Apache Server header version disclosure | configuration_audit |
| Medium | `c733eb58` | Audit Apache enabled modules | configuration_audit |
| Medium | `01d1cd29` | Map full Docker network topology | service_exploit |

Notable planning intelligence: Planning cross-referenced server-status internal IP `172.18.0.4` (obs `03503b17`) with the `pgdatabase` hostname to produce a candidate IP for lateral movement. It also noted that the employee portal login referenced at root page was never located by recon (obs `cc22d737`, `ec116d9b`) and explicitly planned portal endpoint discovery.

---

## Retrieval committee

**Findings:** 34 total — 18 http_head, 7 http_get/extract_links, 9 postgres_query

### Web retriever actions

Executed against plan actions `3bce2610` (deep enumerate /files/), `99fe04cf` (portal login discovery), `093c454c` (API key endpoint probing), `b4671adb`/`9c5146c6`/`d03741db`/`1694ea6f`/`99139d51` (remediation status verification):

**Deep /files/ enumeration (action `3bce2610`):** Probed `credentials.json.bak`, `config.json`, `.env`, `secrets.json`, `database.sql`, `id_rsa` — all 404. `credentials.json` is the sole file currently exposed.

**Portal login discovery (action `99fe04cf`):** Probed `/login`, `/auth`, `/portal`, `/employee`, `/sso`, `/signin`, `/account` — all 404. The employee portal login remains unlocated. Root page contains the text "Please log in via the employee portal" but has zero hyperlinks.

**API key endpoint probing (action `093c454c`):** Probed `/api/v1`, `/api/v2`, `/v1`, `/v2`, `/internal` — all 404. The API service accepting `ik_prod_a1b2c3d4e5f6` is not on this container; it targets a separate internal microservice.

**Remediation status verification:** All five flagged misconfigurations confirmed still active and unpatched:
- `credentials.json` — HTTP 200, plaintext creds confirmed
- Directory listing on `/files/` — HTTP 200, index active
- `/server-status` — HTTP 200, internal IPs and worker PIDs still exposed
- `robots.txt /files/` disclosure — HTTP 200, `Disallow: /files/` still present
- Apache Server header version — `Apache/2.4.52 (Ubuntu)` still disclosed

### Database specialist actions (all under action `d6f48140`)

All 9 queries against `pgdatabase:5432` using `db_admin:Sup3rS3cr3t!2024`:

| Query | Result |
|-------|--------|
| Database enumeration | `postgres` (system), `sarif_prod` (production) |
| User privileges | db_admin: Superuser=True, CreateDB=True — single user account |
| Table enumeration (sarif_prod) | `api_keys`, `employees`, `system_config` |
| `SELECT * FROM api_keys` | 3 keys: `ik_prod_a1b2c3d4e5f6` (active), `mk_mon_x9y8z7w6v5u4` (active, monitoring), `bk_bkp_deprecated` (inactive) |
| `SELECT * FROM employees` | 5 records: jsmith (admin/IT), alee (dev/Eng), bwilson (mgr/Ops), cjones (dev/Eng), dmartin (admin/IT) — all @sarif.corp |
| `SELECT * FROM system_config` | smtp_password=`SarifMail2024!`, backup_encryption_key=`4e6f747468696e67546f536565486572` (AES-256 hex), admin_recovery_code=`SARIF-RECOVERY-2024-XK9P`, vpn_psk=`SarifVPN#SharedKey99` |
| pg_read_file() privilege check | **True** — db_admin can read arbitrary host files via `pg_read_file()` |
| `pg_read_file('/etc/hostname')` | `254fcae1f5b0` — Docker container ID of pgdatabase confirmed |
| `SELECT version()` | PostgreSQL 16.14, Alpine Linux, x86_64 |

**New discovery this run:** pg_read_file() privilege confirmed — extends compromise from database exfiltration to arbitrary file read on the pgdatabase host filesystem (including `/etc/passwd`, SSH keys, application configs).

### Full credential inventory (post-retrieval)

| Secret | Value | Classification |
|--------|-------|----------------|
| PostgreSQL username | db_admin | Confirmed valid |
| PostgreSQL password | Sup3rS3cr3t!2024 | Confirmed valid |
| API key (internal) | ik_prod_a1b2c3d4e5f6 | Confirmed active |
| API key (monitoring) | mk_mon_x9y8z7w6v5u4 | Confirmed active (discovered in DB) |
| API key (backup) | bk_bkp_deprecated | Inactive |
| SMTP password | SarifMail2024! | Plaintext in system_config |
| Backup encryption key | 4e6f747468696e67546f536565486572 | AES-256 hex, plaintext in system_config |
| Admin recovery code | SARIF-RECOVERY-2024-XK9P | Plaintext in system_config |
| VPN pre-shared key | SarifVPN#SharedKey99 | Plaintext in system_config |

### People intelligence

| Username | Role | Department | Email |
|----------|------|------------|-------|
| jsmith | Admin | IT | jsmith@sarif.corp |
| dmartin | Admin | IT | dmartin@sarif.corp |
| alee | Developer | Engineering | alee@sarif.corp |
| cjones | Developer | Engineering | cjones@sarif.corp |
| bwilson | Manager | Operations | bwilson@sarif.corp |

---

## Reporting committee

**Risk rating:** CRITICAL  
**Sections:** 4 — Technical Findings, Risk Assessment, Vulnerability Chain Summary, Unremediated Exposure Status  
**Recommendations:** 15  

### Vulnerability chain (as documented by reporting committee)

```
1. robots.txt Disallow: /files/          — breadcrumb, no brute force needed
2. Apache mod_autoindex on /files/       — credentials.json hyperlinked in index
3. HTTP GET /files/credentials.json      — plaintext db_admin:Sup3rS3cr3t!2024
4. TCP → pgdatabase:5432                 — lateral movement, superuser auth
5. SELECT * FROM sarif_prod tables       — full database exfiltration
6. pg_read_file('/etc/hostname')         — arbitrary host file read confirmed
```

Total attacker effort: unauthenticated HTTP requests + one PostgreSQL connection. No CVE exploitation, no brute force, no malware.

### Recommendations summary

| Priority | Recommendation |
|----------|----------------|
| **IMMEDIATE** | Rotate all 7 exposed secrets (db_admin password, 2 API keys, SMTP password, VPN PSK, admin recovery code, backup encryption key) |
| **IMMEDIATE** | Remove or deny-all `/files/credentials.json` from web root |
| **IMMEDIATE** | Add `Require local` to `<Location /server-status>` or disable mod_status |
| High | Disable directory listing: `Options -Indexes` on /files/ and audit all other web dirs |
| High | Remove `Disallow: /files/` from robots.txt |
| High | Full incident response: audit mail logs, revoke VPN sessions, reset admin accounts |
| High | Locate and test employee portal login (virtual host enumeration, Host header manipulation) |
| High | Revoke db_admin superuser; create least-privilege application service accounts |
| High | `ServerTokens Prod` + `ServerSignature Off` to suppress version disclosure |
| Medium | Enumerate SSH auth methods; test credential reuse on SSH if password auth confirmed |
| Medium | Full Apache module audit (`apache2ctl -M`); disable non-required modules |
| Medium | Assess CVE-2023-38408 (SSH agent forwarding RCE) for OpenSSH 8.9p1 |
| Medium | Enable PostgreSQL statement audit logging; review logs from 2026-07-01 onward |
| Medium | Map full 172.18.0.0/24 Docker network topology; locate API service for exposed keys |
| Low | Implement secrets management (Vault/Secrets Manager); prohibit plaintext web-accessible credentials; enforce HTTPS internally |

---

## Open questions / attack surface not fully covered

1. **SSH password auth** — not confirmed enabled or disabled. If enabled, `db_admin:Sup3rS3cr3t!2024` may allow direct shell access to the target container.
2. **Employee portal login** — referenced on the root page but no endpoint discovered at any standard path. Virtual host enumeration (Host: `sarif.internal`, `portal.sarif`, `intranet`) not yet attempted.
3. **API service for ik_prod_a1b2c3d4e5f6 and mk_mon_x9y8z7w6v5u4** — no endpoint found on target:80. The service lives elsewhere on 172.18.0.0/24 and has not been identified.
4. **Full Docker network topology** — only `target` (172.18.0.2) and `pgdatabase` (254fcae1f5b0, IP inferred from server-status as 172.18.0.4) are confirmed. Other containers on 172.18.0.0/24 unknown.
5. **CVE-2024-6387 (regreSSHion)** — patch status for OpenSSH 8.9p1 Ubuntu 3ubuntu0.15 not definitively confirmed against USN-6859-1.
6. **pgdatabase host filesystem** — pg_read_file() confirmed functional but only /etc/hostname was read. Full host enumeration (/etc/passwd, /etc/shadow, SSH keys) not performed.

---

## Baseline metrics (for run comparison)

| Metric | Value |
|--------|-------|
| Recon observations | 66 |
| signal_warn | 15 |
| signal_info | 10 |
| noise | 41 |
| Plan actions | 14 |
| Retrieval findings | 34 |
| Postgres queries | 9 |
| Tables exfiltrated | 3 (api_keys, employees, system_config) |
| Credentials harvested | 9 |
| Report recommendations | 15 |
| Report sections | 4 |
| Total run time | 13m 38s |
| credentials.json exposure duration at time of run | ≥ 5 days (file dated 2026-07-01) |
