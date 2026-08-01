"""Skill: close_shell — tear down a reverse shell session."""

from __future__ import annotations

import sys
import types


def _sessions() -> dict:
    key = "_athena_htb_shell_sessions"
    if key not in sys.modules:
        m = types.ModuleType(key)
        m.data = {}
        sys.modules[key] = m
    return sys.modules[key].data  # type: ignore[attr-defined]


def close_shell(session_id: str) -> dict:
    sessions = _sessions()
    conn = sessions.pop(session_id, None)
    if conn is None:
        return {"error": f"Session '{session_id}' not found", "closed": None}
    try:
        conn.close()
    except Exception:
        pass
    return {"closed": session_id}
