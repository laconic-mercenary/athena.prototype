"""Skill: run_cmd — execute a command in an active reverse shell session."""

from __future__ import annotations

import shlex
import sys
import types
import uuid


def _sessions() -> dict:
    key = "_athena_htb_shell_sessions"
    if key not in sys.modules:
        m = types.ModuleType(key)
        m.data = {}
        sys.modules[key] = m
    return sys.modules[key].data  # type: ignore[attr-defined]


def run_cmd(session_id: str, cmd: str, timeout: int = 15, stdin: str | None = None) -> dict:
    conn = _sessions().get(session_id)
    if conn is None:
        return {
            "session_id": session_id,
            "error": f"No active shell session '{session_id}'. Call get_shell first.",
            "output": "",
        }

    sentinel = f"__DONE_{uuid.uuid4().hex[:8]}__"
    if stdin is not None:
        # Pipe input into the command so it needs no TTY — e.g. `sudo -S` reading a
        # password from stdin. The reverse shell is a dumb pipe (not a terminal), so
        # commands that would otherwise prompt interactively hang; this feeds them
        # instead. shlex.quote keeps special characters in the input intact.
        line = f"printf '%s\\n' {shlex.quote(str(stdin))} | {cmd}; echo {sentinel}"
    else:
        line = f"{cmd}; echo {sentinel}"
    try:
        conn.sendline(line.encode())
        raw = conn.recvuntil(sentinel.encode(), timeout=timeout)
        output = raw.decode(errors="replace").replace(sentinel, "").strip()
        return {"session_id": session_id, "output": output}
    except Exception as e:
        return {
            "session_id": session_id,
            "error": f"Shell read error: {e}",
            "output": "",
        }
