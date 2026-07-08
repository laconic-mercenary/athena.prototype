# Run 2 — Engagement Findings

**Run ID:** `4743b378-6d41-4ea3-b677-e27e3e03407d`  
**Date:** 2026-07-06  
**Target:** `target` (Sarif Industries Internal Portal — `172.18.0.2`)  
**Duration:** 11 min 20 sec (06:31:59 → 06:43:19 UTC)  
**Overall risk rating:** CRITICAL  

---

## Pipeline timing

| Committee | Started | Completed | Duration |
|-----------|---------|-----------|----------|
| Recon | 06:31:59 | 06:38:01 | 6m 02s |
| Planning | 06:38:01 | 06:39:58 | 1m 57s |
| Retrieval | 06:39:58 | 06:41:26 | 1m 28s |
| Reporting | 06:41:26 | 06:43:19 | 1m 53s |

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
| HTTPS | Not present |
| Database | pgdatabase:5432 (separate container, internal network only) |

---

## Recon committee

**Observations:** 34 total — 9 `signal_warn`, 9 `signal_info`, 16 `noise`

**Specialists registered:** 6 — leader + network_operator (×2) + service_operator (×1) + web_operator (×2)  
Phase 3 re-summoned web_operator and network_operator; service_operator was not re-summoned.

### signal_warn findings

| Obs ID | Category | Command | Finding |
|--------|----------|---------|---------|
| `42003d8f` | exposure | http_get /robots.txt | `User-agent: * Disallow: /files/` confirmed — advertises sensitive path |
| `1b5af4d0` | configuration | http_head /server-status | Apache mod_status accessible — HTTP 200, no auth |
| `4ca8033b` | configuration | http_get /server-status | Full body retrieved — server info, uptime, load, process details |
| `48b68eb0` | configuration | http_head /files/ | Directory listing enabled — HTTP 200, no auth (CWE-548) |
| `3b8caafe` | exposure | http_get /files/ | Directory index contains credentials.json |
| `d8cbe77e` | exposure | extract_links /files/ | 6 links including credentials.json hyperlink |
| `1a1460a0` | authentication | http_get /files/credentials.json | Plaintext creds: `db_admin:Sup3rS3cr3t!2024`, `pgdatabase:5432`, `ik_prod_a1b2c3d4e5f6` |
| `73a04c25` | authentication | http_get /files/credentials.json (Phase 3) | Full JSON body re-confirmed: production credentials |
| `68a74e79` | configuration | http_get /server-status (Phase 3) | Apache/2.4.52, MPM, worker state, load averages — CWE-497 |

### Credentials harvested by recon

| Secret | Value | Source |
|--------|-------|--------|
| PostgreSQL host | pgdatabase:5432 | credentials.json |
| PostgreSQL username | db_admin | credentials.json |
| PostgreSQL password | Sup3rS3cr3t!2024 | credentials.json |
| API key | ik_prod_a1b2c3d4e5f6 | credentials.json |

### Threat analyst output (Foundation-Sec)

```
### CVE Candidates
(no CVEs identified based on available version information)

### Risk Indicators
- Apache Server-Status Exposure: Unauthenticated /server-status reveals live server metrics, process IDs, resource usage
- Credentials File Leakage: Plaintext credentials.json in /files/ contains database credentials and API keys

### Recommended Follow-up
- Web Operator: verify credentials file contents and permissions; disable directory listing; restrict /files/ access
- Network Operator: check firewall rules; audit active sessions
- All Operators: document findings; initiate credential rotation; review server hardening compliance

### Assessment
Critical vulnerabilities exist due to unauthenticated exposure of Apache server metrics and plaintext credential storage.
Immediate containment of both exposures required to prevent lateral movement.
```

**Notes:** CVE assessment was honest this run — "(no CVEs identified)" rather than a placeholder. Recommended follow-up included shell command blocks (format violation against the no-code-blocks instruction), but risk identification was accurate.

### Recon leader summary

> The target container (172.18.0.2) exposes two services: OpenSSH 8.9p1 on port 22 and Apache 2.4.52 on port 80 — no CVEs were identified for these specific builds, but two critical web misconfigurations were confirmed. First, Apache mod_status is enabled and unauthenticated at /server-status, leaking real-time operational data including worker PIDs, client IPs, VHost bindings, and live request paths. Second, and most critically, Apache directory listing is enabled on /files/ with no authentication, exposing credentials.json containing production PostgreSQL credentials and an API key in plaintext.

---

## Planning committee

**Actions generated:** 12

| Priority | ID | Title | Category |
|----------|----|-------|----------|
| Critical | `fb0e9e1f` | SSH credential reuse test | credential_access |
| Critical | `29887989` | PostgreSQL lateral movement via pgdatabase | credential_access |
| Critical | `99db4e9d` | Audit logs for prior credential access | configuration_audit |
| Critical | `3ebba906` | Remove credentials.json and lock /files/ directory | configuration_audit |
| Critical | `a2618a2b` | Restrict Apache mod_status to localhost | configuration_audit |
| High | `ff31b228` | API key enumeration and endpoint discovery | web_enumeration |
| High | `29c8ba9e` | Rotate all exposed production credentials | credential_access |
| High | `78fb8f66` | Probe login portal for authentication bypass | web_enumeration |
| High | `23a6f657` | Suppress Apache version header disclosure | configuration_audit |
| Medium | `0deec72f` | Cleartext HTTP credential interception assessment | configuration_audit |
| Medium | `ceb42c82` | SSH authentication method and cipher audit | configuration_audit |
| Medium | `0bde91d4` | Remove /files/ path from robots.txt | configuration_audit |

---

## Retrieval committee

**Findings:** 27 total — 15 http_get, 5 http_head, 1 extract_links, 6 postgres_query

### Postgres queries (db_specialist)

| Query | Result |
|-------|--------|
| Database enumeration | postgres (system), sarif_prod (production) — lateral movement confirmed |
| Table enumeration (sarif_prod) | employees, api_keys, system_config |
| `SELECT * FROM employees` | 5 records: jsmith (admin/IT), alee (dev/Eng), bwilson (mgr/Ops), cjones (dev/Eng), dmartin (admin/IT) — all @sarif.corp |
| `SELECT * FROM api_keys` | ik_prod_a1b2c3d4e5f6 (active), mk_mon_x9y8z7w6v5u4 (active, monitoring), bk_bkp_deprecated (inactive) |
| `SELECT * FROM system_config` | smtp_password=SarifMail2024!, backup_encryption_key=4e6f747468696e67546f536565486572, admin_recovery_code=SARIF-RECOVERY-2024-XK9P, vpn_psk=SarifVPN#SharedKey99 |
| `SELECT version()` | PostgreSQL 16.14, Alpine Linux, x86_64 |

**Note:** Superuser privilege check and pg_read_file() capability assessment were not performed this run (6 queries vs 9 in Run 1).

### Full credential inventory (post-retrieval)

| Secret | Value |
|--------|-------|
| PostgreSQL password | Sup3rS3cr3t!2024 |
| API key (internal) | ik_prod_a1b2c3d4e5f6 (confirmed active) |
| API key (monitoring) | mk_mon_x9y8z7w6v5u4 (confirmed active) |
| API key (backup) | bk_bkp_deprecated (inactive) |
| SMTP password | SarifMail2024! |
| Backup encryption key | 4e6f747468696e67546f536565486572 |
| Admin recovery code | SARIF-RECOVERY-2024-XK9P |
| VPN pre-shared key | SarifVPN#SharedKey99 |

### People intelligence

| Username | Role | Department |
|----------|------|------------|
| jsmith | Admin | IT |
| dmartin | Admin | IT |
| alee | Developer | Engineering |
| cjones | Developer | Engineering |
| bwilson | Manager | Operations |

---

## Reporting committee

**Risk rating:** CRITICAL  
**Sections:** Technical Findings, Risk Assessment, Scope of Compromise and Blast Radius, Findings Summary Table  
**Recommendations:** 13 (with explicit time-bounded priorities)

### Findings summary table (as generated)

| Severity | Finding | Status |
|----------|---------|--------|
| Critical | Plaintext production credentials in /files/credentials.json | Confirmed exploited |
| Critical | Successful lateral movement to production PostgreSQL | Confirmed exploited |
| Critical | Employee PII exfiltration (5 records) | Confirmed exfiltrated |
| Critical | Additional API keys exposed (mk_mon_x9y8z7w6v5u4) | Confirmed compromised |
| Critical | System secrets in plaintext (SMTP, VPN PSK, recovery code, backup key) | Confirmed exfiltrated |
| High | Apache mod_status unauthenticated exposure | Confirmed active |
| High | Apache directory listing on /files/ | Confirmed active |
| Medium | Apache version header disclosure | Confirmed active |
| Medium | robots.txt /files/ path disclosure | Confirmed active |
| Low | Cleartext HTTP serving internal application | Confirmed active |

### Recommendations (time-bounded)

| Timeframe | Recommendation |
|-----------|----------------|
| Within 1 hour | Rotate db_admin password, revoke all 3 API keys |
| Within 1 hour | Delete /files/credentials.json from web root |
| Within 2 hours | Restrict mod_status with `Require local` |
| Within 4 hours | Review Apache access logs for prior access since 2026-07-01 |
| Within 4 hours | Disable directory listing globally (`Options -Indexes`) |
| Within 4 hours | Deploy TLS on port 443 with HTTP→HTTPS redirect |
| Within 8 hours | Audit SSH: confirm PasswordAuthentication=no |
| Within 8 hours | Suppress Apache version: ServerTokens Prod + ServerSignature Off |
| Within 24 hours | Revoke db_admin superuser; create least-privilege service account |
| Within 24 hours | Remove `Disallow: /files/` from robots.txt |
| Within 48 hours | Container-wide secrets audit across 172.18.0.0/16 network |
| Within 48 hours | Implement centralised log aggregation + alerting |
| Within 1 week | Security awareness training for dev/ops staff |

---

## Baseline metrics

| Metric | Value |
|--------|-------|
| Recon observations | 34 |
| signal_warn | 9 |
| signal_info | 9 |
| noise | 16 |
| Plan actions | 12 |
| Retrieval findings | 27 |
| Postgres queries | 6 |
| Tables exfiltrated | 3 (api_keys, employees, system_config) |
| Credentials harvested | 8 |
| Report recommendations | 13 |
| Report sections | 4 |
| Total run time | 11m 20s |
