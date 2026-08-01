"""Skill: run_cmd — execute a command in an active reverse shell session."""

from __future__ import annotations

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


def run_cmd(session_id: str, cmd: str, timeout: int = 15) -> dict:
    conn = _sessions().get(session_id)
    if conn is None:
        return {
            "session_id": session_id,
            "error": f"No active shell session '{session_id}'. Call get_shell first.",
            "output": "",
        }

    sentinel = f"__DONE_{uuid.uuid4().hex[:8]}__"
    try:
        conn.sendline(f"{cmd}; echo {sentinel}".encode())
        raw = conn.recvuntil(sentinel.encode(), timeout=timeout)
        output = raw.decode(errors="replace").replace(sentinel, "").strip()
        return {"session_id": session_id, "output": output}
    except Exception as e:
        return {
            "session_id": session_id,
            "error": f"Shell read error: {e}",
            "output": "",
        }
