"""Skill: count_extensions — read-only file-extension tally under a directory.

Deterministic Python. The LLM decides *when* to call this and with what directory/extensions;
the implementation decides *how* — and enforces that it stays read-only and inside the allowed
roots. The caller cannot influence those.
"""

from __future__ import annotations

import os

def _get_allowed_roots() -> tuple[str, ...]:
    # SKILL_ALLOWED_ROOTS overrides the default at call time so the SIT can
    # allow /data without modifying this file (set in docker-compose env).
    env = os.environ.get("SKILL_ALLOWED_ROOTS")
    if env:
        return tuple(os.path.realpath(p) for p in env.split(":") if p)
    return (os.path.realpath(os.path.expanduser("~")),)


def _validate_directory(directory: str) -> str:
    """Resolve and bound-check the directory. Raises ValueError if unusable or out of scope."""
    real = os.path.realpath(directory)
    if not os.path.isdir(real):
        raise ValueError(f"Not a directory: {directory!r}")
    allowed = _get_allowed_roots()
    if not any(real == root or real.startswith(root + os.sep) for root in allowed):
        raise ValueError(f"Directory {directory!r} is outside the allowed roots")
    return real


def count_extensions(
    directory: str,
    extensions: list[str],
    hidden_only: bool,
) -> dict:
    """Walk `directory` read-only and count files by extension (case-insensitive).

    hidden_only=True  → only count files whose name starts with '.'
    hidden_only=False → only count files whose name does NOT start with '.'
    """
    root = _validate_directory(directory)
    tally: dict[str, int] = {ext.lower(): 0 for ext in extensions}
    total = 0
    skipped: list[str] = []

    def _onerror(err: OSError) -> None:
        skipped.append(getattr(err, "filename", str(err)))

    for _dirpath, _dirnames, filenames in os.walk(root, onerror=_onerror, followlinks=False):
        for name in filenames:
            is_hidden = name.startswith(".")
            if hidden_only and not is_hidden:
                continue
            if not hidden_only and is_hidden:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in tally:
                tally[ext] += 1
                total += 1

    return {
        "directory": root,
        "counts": [{"extension": ext.lower(), "count": tally[ext.lower()]} for ext in extensions],
        "total_files": total,
        "skipped": skipped,
    }
