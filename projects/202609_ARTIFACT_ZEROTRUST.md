# 2026-09 Artifact Confidentiality & Zero-Trust Data Handling

Design exploration for applying zero-trust data handling to the Athena harness. Motivated by
a red-team's operational reality: engagement artifacts contain **client crown jewels**
(recovered credentials, harvested records, proof-of-compromise). Today those sit in plaintext
on the operator's disk — a lost laptop or a shared host turns an authorized engagement into a
client breach. Companion to [[202609_ENGAGEMENT_CHAINING.md]] (the two intersect at key access —
see ZT4/ZT-X) and the punch list [[202609_DEFICIENCIES.md]].

Status legend: **ACCEPTED** (known, fine for now) · **OPEN** (needs decision) · **FIXED** ·
**VERIFY** (needs a live check).

Design IDs: **ZT0–ZT6**. ZT0 is the prerequisite seam; everything else depends on it.

---

## Current state — the disk is plaintext

Every artifact write and read in the harness is cleartext, at four call sites:

- **Committee outputs** — [workflow.py:133-135](../src/athena/harness/workflow.py#L133-L135)
  writes `artifacts/<run_id>/<committee>.json` via `artifact_path.write_text(model_dump_json())`.
- **Run log** — [artifacts.py:35-51](../src/athena/artifacts.py#L35-L51): a `FileHandler` on
  `run.log` plus `write_artifact()` `path.write_text()`. The log carries full tool I/O and can
  contain secrets and loot verbatim.
- **Serving route** — [routes/artifacts.py:54-71](../src/athena/server/routes/artifacts.py#L54-L71)
  reads with `path.read_text()` and returns it (optionally rendered). No auth on the route.
- **Orchestrator read-back** — [runner.py:276-281](../src/athena/server/runner.py#L276-L281)
  (`_read_artifact_fn`) and [runner.py:496-516](../src/athena/server/runner.py#L496-L516)
  (`render_artifact`) both `read_text()` directly.

There is no encryption at rest, no key management, no access audit, and no data-lifecycle /
destruction path. `artifacts/` accumulates indefinitely. Confidentiality rests entirely on
filesystem permissions of whatever host the operator ran on.

### What lives in an artifact (the assets)

| Artifact | Sensitivity | Contents |
|---|---|---|
| `exploit.json` | **High** | `data_harvested[]`, `flags` (user/root.txt), `commands_executed[]` — see [exploit_output.py](../tests/ensembles/redteamv1/schemas/exploit_output.py) |
| `lateral.json` (planned) | **Critical** | `credentials[]` (principals + secrets), `compromised_hosts[]` — the loot store from [[202609_REDTEAM_GENERICIZATION.md]] |
| `recon.json` | Medium | target intel, OSINT, discovered origin IPs |
| `run.log` | **High** | full transcript incl. tool I/O; may echo secrets |
| plan / operator chat | Medium | scope, authorization notes, operator reasoning |

---

## Threat model — assume the disk is hostile

Zero-trust means we stop trusting the storage medium, the process, and even the operator's
implicit access. The scenarios we design against:

1. **Host loss / compromise.** Laptop stolen, host popped, backup leaked → plaintext loot =
   second breach layered on the engagement. **Primary driver.**
2. **Multi-client contamination.** One operator's machine holds several clients' loot in one
   `artifacts/` tree. Accidental cross-disclosure; no cryptographic separation.
3. **Secure-destruction obligation.** Engagement contracts routinely mandate provable
   destruction of collected data at close-out. Deleting files is not provable; overwriting is
   fragile. We need a stronger primitive.
4. **Over-broad access / no audit.** Any process or person with FS access reads all loot with
   no trace. `reveal_artifact` ([routes/artifacts.py:74-91](../src/athena/server/routes/artifacts.py#L74-L91))
   opens loot in the OS file browser with no record.
5. **In-transit.** The API serves plaintext; fine on localhost, not for any hosted deployment.

---

## Directions

### ZT0 — Introduce a single `ArtifactStore` seam · OPEN (prerequisite)
Nothing below is buildable while reads/writes are scattered across the four call sites above.
**Direction:** define one `ArtifactStore` abstraction (`put(run_id, name, model) / get(run_id,
name) -> model|text / open_log(run_id)`) and route *every* artifact and log write/read through
it. The default implementation stays plaintext (behaviour-preserving), so ZT0 lands as a pure
refactor with no crypto. Encryption becomes a swap of the store implementation. This is the only
hard dependency for the whole doc — do it first, alone.

### ZT1 — Encrypt artifacts at rest (envelope encryption) · OPEN
**Direction:** the store writes an AEAD envelope instead of raw JSON — on-disk shape roughly
`{ "v":1, "alg":"age"|"secretbox", "epk":…, "nonce":…, "ct":…, "dek_ref":… }` (extension `.enc`).
Each engagement gets a random **Data Encryption Key (DEK)**; the DEK is wrapped by a
**Key Encryption Key (KEK)** held under Athena management (ZT2). AEAD gives us tamper-evidence
(a modified artifact fails to open) on top of confidentiality. `render_full()` / `render_digest()`
run on the decrypted model, unchanged — only the bytes on disk differ.

### ZT2 — Key management: the private key "under Athena management" · OPEN (decision)
The operator framed this as "encrypt with a private key under Athena management." Two shapes:

- **(A) Asymmetric sealing (recommended).** Athena owns an **age (X25519) identity** / libsodium
  sealed-box keypair. Writers seal artifacts to the *public* key; only the operator-side server
  holds the *private* key to open them. **Least-privilege falls out for free:** recon / exploit /
  lateral committees can produce loot without ever holding decryption capability — a compromised
  committee process leaks nothing already sealed. This is the literal reading of "a private key
  under Athena management."
- **(B) Symmetric passphrase KEK.** Operator supplies a passphrase at engagement start; KDF
  (argon2id) → KEK. Simpler, but every writer holds the symmetric key, so no write-only
  least-privilege.

**Direction:** go with (A). The private key material comes from the environment only — reuse the
existing `auth_headers_env` convention: `ATHENA_ARTIFACT_KEY_FILE` names a path to an age
identity mounted at runtime (never baked into the image, never committed). The manifest/config
stores the *name/path*, never the key — same rule as target secrets. Public key can live in
config in the clear. The `dek_ref` indirection keeps a future external KMS (Vault / cloud KMS)
a drop-in without touching the envelope format.

### ZT3 — Per-engagement isolation & crypto-shredding · OPEN
**Direction:** distinct DEK per engagement (wrapped by the shared KEK/identity). Destroying one
engagement's **wrapped DEK** renders that engagement's entire artifact set unrecoverable — a
provable, instantaneous secure-destruction primitive that touches nothing else. This is the
answer to threat #3 and #2: filesystem layout stays `artifacts/<run_id>/`, but confidentiality
and separation no longer depend on FS perms. Optional hardening: a per-*client* KEK for hard
cryptographic separation between clients on a shared operator host.

### ZT4 — Need-to-know within the pipeline · OPEN
Committees already declare what they read via `consumes` in the manifest. **Direction:** the
store enforces it — a committee may decrypt only its declared `consumes` set, not the whole
engagement. Split high-sensitivity **loot** (`credentials`, `data_harvested`) into a sealed
sub-store distinct from routine committee outputs and digests, so broad "read the recon summary"
access never implies "read every recovered secret." This is where zero-trust meets the loot-store
design in [[202609_REDTEAM_GENERICIZATION.md]] — the lateral committee's credential store should
be born sealed.

### ZT5 — Access audit ("never trust, verify") · OPEN
**Direction:** every decrypt of a high-sensitivity artifact emits an audit event (who / when /
which artifact / which engagement) onto a dedicated audit channel — reuse the SSE bus + a
tamper-evident append-only `audit.log`. `get_artifact` and `reveal_artifact` become audited
operations. Reads of loot should be observable after the fact, not silent.

### ZT6 — In-transit & data lifecycle · OPEN
**Direction:** (a) API authentication + TLS for any non-localhost deployment (today the artifact
routes are unauthenticated). (b) Retention policy: a `destroy engagement data` operator action
that wipes the wrapped DEK (ZT3), plus optional auto-shred N days post-close. (c) `run.log` must
be encrypted or scrubbed — it is currently the leakiest surface (plaintext, full I/O). (d)
`reveal in file browser` cannot usefully reveal an encrypted blob → either decrypt-to-a-temp
(audited, auto-wiped) or drop the feature.

---

## Cross-link — where this meets engagement chaining · ZT-X
[[202609_ENGAGEMENT_CHAINING.md]] wants a child engagement to inherit a parent's artifacts. Those
artifacts are sealed per-engagement (ZT3), so **inheritance crosses a key boundary**: the child
must be explicitly authorized to open the parent's DEK. Recommendation: re-wrap the parent's DEK
to the child engagement at transition time, as an operator-gated, audited grant — inheritance
becomes an *explicit* key delegation, not implicit file access. This keeps the zero-trust
posture intact across a chain and gives the operator a clean point to deny propagation of
sensitive loot into a follow-on.

---

## Phasing

- **P0 — ZT0.** The `ArtifactStore` seam, plaintext, behaviour-preserving. Unblocks everything.
- **P1 — ZT1 + ZT2(A) + ZT3.** Sealed artifacts, age identity from env, per-engagement DEK +
  crypto-shred. This alone closes threats #1, #2, #3.
- **P2 — ZT4 + ZT5.** Need-to-know decryption + audit.
- **P3 — ZT6.** Transit auth/TLS, retention automation, log encryption, reveal rework.

---

## Open questions
- **Asymmetric (A) vs symmetric (B)?** Recommending (A) for write-only least-privilege — confirm.
- **Server-side vs browser-side decrypt for the UI?** Recommend server holds the key and decrypts
  on demand; the browser never touches key material. Simpler, keeps one trust boundary.
- **Loot/metadata split granularity (ZT4)** — per-field sealing vs a separate sealed sub-store.
  Sub-store is coarser but far simpler; per-field is stronger but touches every schema.
- **KEK residence in the container** ([run.sh] deployment) — mounted secret / tmpfs, never in the
  image layer. Needs a concrete story before P1.
- **run.log** — encrypt wholesale, or scrub-then-plaintext? Encrypt is safer; scrub is friendlier
  to live tailing during a demo.

## Notes
- ZT0 is the whole unlock. Resist starting P1 crypto before the seam exists — otherwise the
  encryption logic scatters across the same four call sites it was meant to consolidate.
- The asymmetric-sealing choice is doing double duty: at-rest confidentiality **and** in-pipeline
  least-privilege (ZT4). That is the reason to prefer it over a passphrase even though a
  passphrase is a smaller first step.
- Nothing in this doc changes the target-secret rule: keys come from the environment, the
  manifest stores names/paths only, and `.env` is never read.
