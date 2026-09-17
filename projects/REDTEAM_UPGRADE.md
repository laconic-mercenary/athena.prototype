# 2026-09 Red Team Ensemble — Genericization & HTB Specialist Roster

Design plan for turning the demo-specific `redteamv1` ensemble into a general red-team
ensemble capable of engaging **HTB-style Windows and Linux environments**. Companion to
[[HACKTHEBOX.md]] (target scenarios) and [[RECON_PLANNING.md]] (recon/planning design). Captured
after the demo, where — in the interest of time — the agents were "guided" to the exploits via
prompts and by enabling only a narrow set of specialists.

Tier legend: **T1** (no new tooling — prompts + on-disk knowledge only) · **T2** (Windows exec
channels — new skills) · **T3** (Active Directory / lateral movement — new skills + new committee).

---

## Problem statement — where the guidance lives

The pipeline is **generic at both ends and hardcoded in the middle**. Recon, planning, and
reporting already generalize; the exploit committee is welded to the one demo box.

| Committee | Genericity | Notes |
|-----------|-----------|-------|
| recon | 🟢 mostly generic | OSINT→scan→enum→CVE on any domain. OS-check already probes Linux **and** Windows families ([os_fingerprint/impl.py](../tests/ensembles/redteamv1/skills/os_fingerprint/impl.py)). |
| planning | 🟢 generic | Compare-mode planners reason purely from `ReconOutput`. No target assumptions. |
| exploit | 🔴 **fully hardcoded** | Every element is the Meridian box: `flask_exploiter` = PyYAML CVE-2017-18342 at `/api/parse-config`; `redis_operator` = dump `/root/.redis_password`→Redis; privesc = SUID `python3.10`. This is the "guided" layer. |
| reporting | 🟢 generic | Narrative + MITRE mapping from artifacts. |

The vuln is hardcoded into the exploit leader's system prompt
([exploit/leader.yml:5-6](../tests/ensembles/redteamv1/committees/exploit/leader.yml)), and the
only code-execution channels are the Flask YAML RCE and a bash `/dev/tcp` reverse shell — **a
Windows HTB box has no path through this committee at all.** The schema layer is already partly
generalized (`flags: dict[str,str]` in
[exploit_output.py:21](../tests/ensembles/redteamv1/schemas/exploit_output.py)), so this migration
was started and stalled at the exploit committee.

**Direction:** rebuild the exploit committee around *capabilities*, not one CVE; specialize agents
narrowly (many small, conditionally-activated specialists over few broad ones); and give each
specialist its expertise as an **on-disk knowledge file** rather than relying on model recall.

---

## Design principle — knowledge as files on disk

The narrow specialists stay effective on *cheap* models because their expertise is supplied as
bundled reference material (payload libraries, tool-flag cheatsheets, gadget chains, checklists)
injected into their context. **The knowledge file is the specialization; the model is the
executor.** A `deserialization_operator` on a small model with an exact gadget-chain reference
beats a large model guessing payload syntax from memory.

**Direction (convention to lock before building):**
- Per-specialist knowledge lives in the element dir, e.g.
  `elements/deserialization_operator/deserialization_gadgets.md`, referenced from that
  specialist's `task.md`.
- Shared references (`gtfobins.md`, `default_creds.md`) live in an ensemble-level `knowledge/`
  dir, pulled into multiple specialists.
- Decide whether the loader gets a `knowledge:` element field for automatic injection, or the
  prompt `cat`s the file. Automatic injection is cleaner and worth the small loader change.

---

## Full specialist roster

`new_tools` ⭐ = new skill impl required · **mod** = extend `run_cmd` to be shell-aware
(`sh`/`cmd`/`powershell`) · libraries → ensemble
[requirements.txt](../tests/ensembles/redteamv1/requirements.txt), never core `pyproject`.

| Specialist | Activate when | Description | new_tools | Knowledge (files) | Libraries | Tier |
|-----------|---------------|-------------|-----------|-------------------|-----------|------|
| `deserialization_operator` | Plan names insecure deserialization; app takes serialized input (YAML/pickle/Java/PHP/.NET/ViewState) | Deserialization → RCE. Home of the old Flask/PyYAML box. | — | `deserialization_gadgets.md` | — (httpx) | T1 |
| `injection_operator` | Recon/plan flags an injectable param, login form, or DB-backed endpoint | SQLi / NoSQLi / OS-command injection → data or RCE. | — | `injection_payloads.md` | — | T1 |
| `upload_lfi_operator` | Upload form, `?file=`/`?page=` param, or traversal candidate found | File-upload webshell, LFI→RCE, path traversal. | — | `webshells.md`, `lfi_wrappers.md` | — | T1 |
| `auth_bypass_operator` | Login/admin panel, JWT/session cookies, or REST IDs present | Default creds, JWT/session forgery, IDOR, panel bypass. | — | `default_creds.md`, `jwt_attacks.md` | PyJWT | T1 |
| `linux_postex` | Code exec on a **Linux** host confirmed; not yet root | Local privesc: SUID/sudo/cron/caps/PATH/writable-service. | — | `gtfobins.md`, `linux_privesc_checklist.md` | — | T1 |
| `linux_credential_operator` | Any read access on Linux (pre- or post-root) | Harvest shadow, history, env, config secrets, SSH keys. | — | `linux_secret_locations.md` | — | T1 |
| `container_escape_operator` | Foothold identifies as a container (`/.dockerenv`, cgroup hints, mounted socket) | Docker/K8s breakout to host. | — | `container_escapes.md` | — | T1 |
| `windows_postex` | Code exec on a **Windows** host confirmed; not yet SYSTEM | Local privesc: SeImpersonate→potato, unquoted svc, weak ACLs, AlwaysInstallElevated. | **mod** | `windows_privesc_checklist.md`, `potato_selection.md` | — | T1 |
| `datastore_specialist` | Internal datastore (Redis/Mongo/SQL/MSSQL/PG) discovered post-access | Loot any datastore. | — | `datastore_dump_recipes.md` | redis, pymongo, psycopg2-binary, pymysql | T1 |
| `exfil_specialist` | Objective data located and operator approved for collection | Stage, size, retrieve sensitive data. | — | `exfil_staging.md` | — | T1 |
| `powershell_operator` | Windows foothold where cmd is limited/blocked and PS is available | PS exec; exec-policy/AMSI handling; encoded commands. | **mod** | `powershell_tradecraft.md` | — | T2 |
| `windows_registry_operator` | Windows foothold + suspected stored creds/autologon/misconfig | `reg query/add`: autologon, Run keys, AlwaysInstallElevated. | **mod** | `registry_hunting.md` | — | T2 |
| `winrm_operator` | Recon shows WinRM open (5985/5986) **and** valid creds recovered | Command exec over WinRM (evil-winrm style). | `winrm_exec` ⭐ | `winrm_usage.md` | pywinrm | T2 |
| `smb_operator` | SMB open (445); null-session, spray candidate, or valid creds | Share enum, psexec-style exec, file get/put. | `smb_ops` ⭐ | `smb_enum.md` | impacket | T2 |
| `rdp_operator` | RDP open (3389) **and** valid creds recovered | RDP access + non-interactive command exec. | `rdp_exec` ⭐ | `rdp_usage.md` | (xfreerdp binary) | T2 |
| `windows_credential_operator` | SYSTEM/admin on Windows achieved | LSASS/SAM/SYSTEM dump, DPAPI, cached creds. | **mod** + `smb_ops` | `cred_dump_procedures.md` | impacket | T3 |
| `ad_enum_operator` | Host is domain-joined **and** any domain cred obtained | LDAP/BloodHound collection, user/group/ACL enum. | `ad_enum` ⭐ | `bloodhound_queries.md` | bloodhound-python, ldap3, impacket | T3 |
| `kerberos_operator` | Domain confirmed + a roastable account (SPN set / no-preauth) identified | Kerberoast / AS-REP roast / ticket abuse. | `kerberos_ops` ⭐ | `kerberos_attacks.md` | impacket | T3 |
| `ssh_operator` | SSH key/cred recovered that may unlock another host | Key reuse, known_hosts pivots, SSH spray. | `ssh_exec` ⭐ | `ssh_pivot_checklist.md` | paramiko | T3 |
| `pivot_operator` | Foothold reveals an unreachable internal subnet/host | Tunnel to internal hosts (chisel/proxychains/ssh -L). | `pivot_setup` ⭐ | `tunneling_recipes.md` | (chisel/sshuttle binaries) | T3 |
| `password_cracking_specialist` | Hashes captured (from `*_credential_operator` / `kerberos_operator`) | Offline crack — **never touches target**. | `crack_hash` ⭐ | `hashcat_modes.md` | (hashcat/john binaries) | T3 |

### Routing discipline

Two structural notes fall out of the *Activate when* column:

- **The triggers form a dependency graph, not a flat list.** `password_cracking_specialist`
  depends on `*_credential_operator`/`kerberos_operator`; `kerberos_operator` depends on
  `ad_enum_operator` establishing a domain; `winrm/rdp_operator` depend on creds another
  specialist recovered. That chaining is the *credential-access → lateral-movement* loop —
  motivating the separate T3 committee below.
- **Activation keys off two fact sources:** recon-time facts (open ports, domain-joined) and
  post-access discoveries (`/.dockerenv`, recovered creds). The leader can only route on the
  second kind if specialists **report structured discoveries** back into committee working state.
  Bake that contract into the leader/element prompts, or conditional gating stays aspirational.

---

## Exploit committee — genericization (T1)

**Direction:** replace the three Meridian-specific elements with technology-family specialists
the leader activates from what recon/planning found. Strip the CVE/Flask/Redis specifics from the
exploit leader's system prompt; drive off `PlanOutput.primary_vector` + a `target_os` field.

- [exploit/leader.yml](../tests/ensembles/redteamv1/committees/exploit/leader.yml) — becomes:
  *"You receive an approved plan naming a primary vector and target OS. Confirm code execution via
  the vector, establish a foothold, enumerate, escalate — matching the specialist to the
  technology and OS you encounter."* Keep the mandatory `ask_operator` gates (privesc / internal
  host / sensitive data) — already generic and good.
- [exploit/playbook.md](../tests/ensembles/redteamv1/committees/exploit/playbook.md) is already
  **stale** (lists `web_exploiter`/`shell_operator`, not the actual elements). Rewriting it toward
  the generic roster fixes the staleness too.
- [planning task.md](../tests/ensembles/redteamv1/committees/planning/elements/exploit_planner/task.md)
  — add "state the target OS and whether the vector needs an interactive shell (Windows) or
  supports non-interactive RCE (web)" so the exploit leader gets OS routing for free.
- [capability.md](../tests/ensembles/redteamv1/capability.md) — retitle from `redteam-meridian`;
  drop the "non-interactive RCE, no reverse shell needed" Meridian-ism (untrue for Windows).

**`run_cmd` shell-aware mod:** [run_cmd/impl.py](../tests/ensembles/redteamv1/skills/run_cmd/impl.py)
frames output with `; echo <sentinel>`, which assumes a POSIX shell and breaks on
`cmd.exe`/PowerShell. Add a `shell: sh|cmd|powershell` param so the sentinel framing adapts. This
single mod unlocks every **mod** row in the roster.

---

## T3 — Lateral Movement committee topology

### Where it sits

```
recon → planning →[gate]→ exploit →[NEW gate]→ lateral → reporting
                                                  ↑______↓ (internal loop)
```

`exploit` gets the **initial foothold + first-host privesc** (root/SYSTEM on box 0). `lateral`
owns everything that turns one owned host into network/domain compromise — the long, iterative
`cred-access → crack → move → privesc → repeat` loop, maintaining its own loot store.

### The new gate (mandatory `operator_approval` after `exploit`)

1. **Scope/authorization** — lateral movement touches *new hosts* not in the original target.
   That blast-radius decision must be the operator's, like the existing pre-exploit gate.
2. **Pass-through for single-box targets** — most HTB standalone boxes have no lateral surface.
   If the operator declines (or the leader sees no internal hosts/domain), `lateral` immediately
   `finish()`es (`notes: "single-host target, no lateral surface"`) → reporting. The committee is
   always present in the graph but no-ops when irrelevant.

### Committee spec — `lateral` (Lateral Movement & Credential Access)

- **model:** `claude-sonnet-4-6` (leader needs strong multi-host state tracking)
- **max_steps:** ~50 (the long committee)
- **consumes:** `exploit` (required — foothold host, access level, creds/data already surfaced),
  `recon` (optional — host/subnet map), `planning` (optional)
- **mode:** action committee, single specialist per element, no compare/`select_result`

**Elements** — note the reuse: movement channels (`winrm`/`smb`/`ssh`) and post-ex
(`windows_postex`/`linux_postex`) are the *same elements declared into this committee too*; only
credential-access + pivot + cracking are net-new. Lateral movement is a recomposition of exec +
cred primitives, not a pile of new code.

| Element | Role in the loop | Skills | Tier origin |
|---------|------------------|--------|-------------|
| `ad_enum_operator` | Map the domain: users, groups, ACLs, attack paths | `ad_enum` | T3 |
| `windows_credential_operator` | Dump LSASS/SAM/NTDS, DPAPI, cached creds | `run_cmd`, `smb_ops` | T3 |
| `linux_credential_operator` | Harvest keys/shadow/config secrets on Linux hops | `run_cmd` | T1 (reused) |
| `kerberos_operator` | Kerberoast / AS-REP roast / ticket abuse | `kerberos_ops` | T3 |
| `password_cracking_specialist` | Offline crack of captured hashes — no target touch | `crack_hash` | T3 |
| `winrm_operator` | **Movement:** land on next Windows host via WinRM | `winrm_exec` | T2 (reused) |
| `smb_operator` | **Movement:** psexec-style exec to next Windows host | `smb_ops` | T2 (reused) |
| `ssh_operator` | **Movement:** key-reuse / spray to next Linux host | `ssh_exec` | T3 |
| `pivot_operator` | Tunnel to otherwise-unreachable subnets | `pivot_setup` | T3 |
| `windows_postex` | Local privesc on each newly-landed Windows host | `run_cmd` | T1 (reused) |
| `linux_postex` | Local privesc on each newly-landed Linux host | `run_cmd` | T1 (reused) |

### The internal loop the leader drives

```
1. ENUM      → ad_enum_operator (if domain-joined) / host+subnet enum
2. HARVEST   → *_credential_operator, kerberos_operator    → into loot store
3. CRACK     → password_cracking_specialist (offline)      → into loot store
4. [gate]    → ask_operator: approve reaching host N with these creds
5. MOVE      → winrm/smb/ssh_operator lands on host N
6. PRIVESC   → windows/linux_postex on host N
7. loop to 1 from the new host, until domain-admin / objective / hosts exhausted
```

The leader keeps the loot store + host graph in committee working state across steps; the
`LateralOutput` schema persists it at `finish()`.

### Output schema (`schemas/lateral_output.py`, sketch)

```python
class Credential(BaseModel):
    principal: str          # user / account / SPN
    secret_type: str        # password | ntlm_hash | kerberos_ticket | ssh_key
    source_host: str
    source_technique: str   # T-id / how obtained
    cracked: bool = False

class CompromisedHost(BaseModel):
    host: str
    os: str                 # windows | linux
    access_level: str       # user | admin | system | root | domain_admin
    entry_technique: str    # winrm | smb | ssh | rdp | exploit
    from_host: str          # pivot origin — this field is the graph edge
    domain_joined: bool = False

class LateralOutput(BaseModel):
    domain: str = ""
    compromised_hosts: list[CompromisedHost] = []
    credentials: list[Credential] = []
    highest_privilege: str = ""      # "Domain Admin" | "root on db01"
    lateral_techniques: list[str] = []
    objective_reached: bool = False
    notes: str = ""
```

`from_host` is deliberately a compromise-graph edge — reporting can render the full pivot chain.
**Open decision:** whether `Credential` stores raw secret values or redacted refs in the persisted
artifact (it feeds the report and is written to disk). Default suggestion: store NTLM hashes,
redact cleartext/keys to a ref — but this is a demo-context call.

### Mandatory `ask_operator` moments (stricter than exploit — every action can widen scope)

| Moment | Include in the question |
|--------|-------------------------|
| Moving to each **new host** | Target host, creds/technique, why it's in scope |
| Dumping **domain** creds (NTDS.dit / DCSync) | The DC, the method, expected blast radius |
| Touching a **domain controller** at all | DC identity + intended action |

### Manifest / workflow deltas

```yaml
# workflow: reroute exploit's success edge through lateral
exploit:
  transitions:
    - to: lateral          # was: reporting
    - to: exploit { condition: retry }
    - to: exploit { condition: iterate }
lateral:
  output_schema: schemas.LateralOutput
  transitions:
    - to: reporting
    - to: lateral { condition: retry }
    - to: lateral { condition: iterate }
reporting:
  consumes:
    required: [exploit]
    optional: [recon, planning, lateral]   # + lateral
```

Plus the new gate in [capability.md](../tests/ensembles/redteamv1/capability.md)'s gate table
(`After: exploit → operator_approval`).

---

## Phasing

- **T1 (no new tools):** `web_*` split, `linux_postex`, `windows_postex`, `linux_credential_operator`,
  `container_escape_operator`, `datastore_specialist`, `exfil_specialist` + shell-aware `run_cmd`.
  Covers all Linux HTB and Windows local-privesc. Prompt-only genericization of the exploit leader
  + playbook is the reversible first move that unblocks the rest.
- **T2 (Windows exec channels):** `winrm_operator`, `smb_operator`, `powershell_operator`,
  `windows_registry_operator`, `rdp_operator`. Real Windows footholds.
- **T3 (AD + lateral movement):** the `lateral` committee — `ad_enum_operator`,
  `kerberos_operator`, `windows_credential_operator`, `ssh_operator`, `pivot_operator`,
  `password_cracking_specialist`. Full AD kill chain.

---

## Open questions
- **Knowledge injection mechanism** — loader `knowledge:` field vs prompt `cat`. Blocks the
  on-disk-knowledge convention (decide first — everything else depends on it).
- **Credential storage in artifacts** — raw vs redacted refs in `LateralOutput` on disk.
- **Structured-discovery contract** — leader/element prompts must return machine-readable
  discoveries (creds, hosts, OS) for conditional activation to work.
- **Reporting must consume `LateralOutput`** — `report_writer` + `mitre_mapper` render the
  compromise graph + full technique chain. Small change, easy to forget.
- **Routing dilution** — ~20 specialists means the leader must route correctly every step;
  conditional-activation prompts (the old `redis_operator` pattern) are the mitigation.
- **Tooling reality** — ⭐ rows imply real external tooling (evil-winrm/impacket/BloodHound/chisel/
  hashcat) not in the harness image today; those specialists are inert until their skill exists.

## Notes
- This plan is the ensemble-side counterpart to the harness/UX punch list in
  [[202609_DEFICIENCIES.md]]. Sequencing here is independent of that list.
- The `flags` schema field and the dual-OS recon fingerprint show the genericization was already
  begun; this doc completes it.
