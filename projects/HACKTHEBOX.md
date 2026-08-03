# Hack The Box — engagement model & pipeline constraints

How the `redteamv1` ensemble maps onto a real Hack The Box (HTB) engagement, and the
constraints that decide whether it can reach root. Run via `tests/system/redteam_htb/`.

---

## What "solving" a box means

There is no "solution" to submit — you capture two **flag** strings:

| Flag | Location | Proves |
|---|---|---|
| **user.txt** | a low-privilege user's home dir | you gained a **foothold** (initial access) |
| **root.txt** | `/root/root.txt` | you gained **root** (privilege escalation) |

Each flag is a 32-hex string. You paste them into the **HTB machine page** to score the
box ("user owned" / "system owned"). The pipeline *captures* the flags; the operator
*submits* them — there is no HTB API in this flow.

### What the flags actually are (and what they are not)

A flag is a **scoreboard token, not the objective**. The file contents are worthless —
what matters is the **access you had to gain to read it**. To `cat /root/root.txt` you must
*be root*, and root on a box means you own everything on it (files, credentials, any
database running there). So the flag is a standardized, machine-checkable **proof of
access level** — HTB uses it because it is automatable and needs no real sensitive data on
practice boxes.

Two consequences worth keeping straight:

- **It's foothold + privesc, not just privesc.** `user.txt` proves initial access as *some*
  user; `root.txt` proves escalation to full control. Two distinct rungs.
- **Real engagements are objective-driven; HTB is access-driven.** A real red team is scored
  on reaching a specific asset ("exfiltrate the PII database"), and root may not even be
  required if the crown jewel is readable at foothold. HTB always pushes to root because
  "demonstrate full compromise" is the *training* goal. On many boxes the database/golden-egg
  *is* part of the path to the flag (SQL-inject a DB → creds → foothold → root) — but the
  flag, not the DB, is what gets submitted.

### Scope

HTB **Machines** are standardized on the two-flag model — individual machines do not set
custom objectives; only the exploitation *path* varies. Other HTB content types differ and
are **out of scope** for this pipeline:

| Content type | Win condition | Fit |
|---|---|---|
| **Machine (Linux)** | `user.txt` + `root.txt` | ✅ target |
| **Machine (Windows)** | same files on Desktops; root = Administrator/SYSTEM | ❌ no Linux shell / `sudo` / `run_cmd` |
| **Challenge** (web/crypto/pwn/rev) | single embedded `HTB{...}`, often no shell | ❌ different game |
| **Sherlock** (DFIR) | answer investigation questions | ❌ no exploitation |
| **Pro Labs / Fortress / Endgame** | multi-machine, many flags, pivoting | ❌ beyond scope |

The `scope` brief field ("full compromise — user.txt + root.txt") is the operator telling
the pipeline which flags to pursue — the closest thing to a per-engagement objective, and
it is set by **you**, not the box. Stick to **Linux Machines** — what `redteamv1` is built for.

---

## Kill chain → committees

| Stage | Meaning | Committee |
|---|---|---|
| **Enumerate** | scan ports/services, map the attack surface | `recon` (nmap, web_enum, searchsploit) |
| **Choose a vector** | pick the exploit path, MITRE-map it | `planning` → **operator-approval gate** |
| **Foothold** | exploit an exposed service → shell as a low-priv user → **user.txt** | `exploit` / web_exploiter → `get_shell` |
| **Privilege escalation** | escalate low-priv shell → root → **root.txt** | `exploit` / shell_operator (`run_cmd`) |
| **Report** | findings + remediation | `reporting` |

---

## How the exploit leader drives it

A just-in-time step loop (`committees/exploit/leader.yml`):

1. **Probe** — `http_get`/`http_post` to confirm the target and inspect the endpoint.
2. **Exploit** — `get_shell(lhost, lport, exploit_url, exploit_body)`: starts the listener
   and delivers the payload atomically; the reverse shell calls back to `lhost` (tun0) and
   returns a `session_id`.
3. **Shell ops** — `run_cmd(session_id, cmd)` in the persistent session: `whoami` →
   `find / -name user.txt` → `cat user.txt` → `sudo -l` / SUID hunt → privesc → `cat /root/root.txt`.
4. **Finish** — `close_shell`, then synthesise `ExploitOutput`.

The leader **must `ask_operator` before** reading any flag, running privesc, modifying the
system, or pivoting to a new host — so the operator approves at each sensitive moment.

---

## Operator role (human in the loop)

1. Connect OpenVPN; get the **target IP** from the HTB machine page.
2. Start the engagement: `target`, `lhost` (tun0 IP), `lport`, `scope` (e.g. "full
   compromise — user.txt + root.txt").
3. **Approve the plan** at the gate.
4. **Approve** flag-reads / privesc when the leader asks.
5. **Submit** the captured flag strings on the HTB machine page.

---

## Known constraints / problems

### 1. Step ceiling (`max_steps`)

The exploit committee's `max_steps` (manifest, per-committee; default 12) is the hard
ceiling for the whole exploitation phase — there is **no self-loop** for exploit.
Enforcement is graceful: at the cap, `submit_step` returns "Step cap reached — call finish()
now" and the committee wraps up (marked incomplete).

- **Configurable?** Yes — a one-line manifest edit, bind-mounted, live next engagement. No
  rebuild.
- **Implication of bumping:** every step is a leader LLM turn + an element specialist LLM
  call (+ tool exec + possibly an operator prompt), so more steps = more cost, latency, and
  operator interaction — but a much better chance of reaching root on a box that needs real
  enumeration.
- **Status: raised to `max_steps: 40`** (was 14) to give foothold + enumeration + privesc +
  both flags real headroom.

### 2. Privilege escalation reliability

**Privesc** = going from the low-privilege account the foothold lands you in (often a service
user like `www-data`) to **root**. Needed because the exploited service rarely runs as root,
and `root.txt` is only readable by root.

Common Linux vectors the shell_operator enumerates and abuses:
- **sudo misconfig** — `sudo -l` shows commands runnable as root; many are abusable (GTFOBins).
- **SUID binaries** — `find / -perm -4000`; setuid-root binaries that can execute code.
- **Cron jobs** — root-run scripts that are world-writable → inject code.
- **Kernel exploits** — vulnerable kernel version → local root exploit.
- **Credential reuse** — passwords/keys on disk reused for a higher-priv account.

This is the **least reliable stage**: it's open-ended reasoning over enumeration output.
Claude handles common vectors well; novel or chained privesc is hit-or-miss.

### 3. Non-TTY shell (TTY / PTY / sentinel)

- **TTY** (teletypewriter) — a terminal interface. A "real TTY" lets programs prompt for
  input (passwords), handle signals (Ctrl-C), and control the screen (editors, `top`).
- **PTY** (pseudo-terminal) — a software-emulated TTY. SSH sessions and terminal windows
  run on PTYs. Upgrading a dumb shell to a PTY
  (`python3 -c 'import pty; pty.spawn("/bin/bash")'`) is the standard way to make a reverse
  shell interactive.
- **Sentinel** — in our `run_cmd`, a unique marker: the skill sends `<cmd>; echo __DONE_ab12__`
  and reads the shell output **until** it sees `__DONE_ab12__`. That marker is how a
  non-interactive one-shot executor knows where the command's output ends.

The problem: a raw reverse shell (`bash -i >& /dev/tcp/...`) is **not a TTY** — it's a dumb
pipe. Programs that require a terminal — `sudo` password prompt, `su`, `ssh`, `vim`,
anything using `getpass` — detect no TTY and hang waiting for input. Our sentinel never
prints, so `run_cmd` **times out** with no output.

- **Works well:** non-interactive privesc — sudo NOPASSWD, SUID abuse, cron, kernel exploit
  that drops a root shell, writing an SSH key.
- **Struggles:** anything needing interactive input.

**Mitigation options (cheapest first):**
- **A — `sudo -S` / stdin (DONE).** `run_cmd` now takes a `stdin` field piped to the
  command over a pipe (no TTY). The leader briefs `sudo -S <cmd>` + the password as stdin.
  Covers the most common interactive case (sudo password) for cheap. Implemented in
  `skills/run_cmd/` + shell_operator/leader prompts.
- **B — real PTY upgrade (not done, medium-high).** Spawn a PTY
  (`python3 -c 'import pty;pty.spawn("/bin/bash")'`) and replace the sentinel reader with a
  `pexpect`-style prompt-matcher. The hard part is the read side — echoed input, prompts,
  and ANSI pollute `recvuntil`. Only needed for boxes requiring full interactivity (`su`,
  full-screen tools).
- **C — dedicated interactive-shell specialist (not done, orthogonal).** A shell_operator
  that holds the session and runs a bounded multi-command loop within one step, cutting
  leader round-trips. Speeds enumeration/privesc; sits on top of A or B.

### 4. Foothold must be a constructible web payload

`get_shell`/`http_post` deliver a single HTTP request. Works for boxes with a documented
web-RCE (command injection, deserialization, auth-bypass → upload → RCE). Won't do binary
exploitation, brute-force-heavy footholds, or multi-stage chains.

### 5. Not a fit

Windows/AD boxes; binary/buffer-overflow exploitation; boxes needing heavy manual pivoting.

---

## Recommended first box

An **easy, retired, Linux** box with a **web-based foothold**. Best odds of the pipeline
reaching at least user.txt (often root), and the cleanest demo. Avoid Windows/AD,
overflow, and heavy-enumeration boxes for the first run.
