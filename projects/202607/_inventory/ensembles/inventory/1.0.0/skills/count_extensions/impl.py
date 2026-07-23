"""Skill: count_extensions — read-only file-extension tally under a directory.

Deterministic Python. The LLM decides *when* to call this and with what directory/extensions;
the implementation decides *how* — and enforces that it stays read-only and inside the allowed
roots. The caller cannot influence those.
"""

from __future__ import annotations

import os

# Read-only scope. The directory must resolve inside one of these roots. Defaults to the user's
# home; adjust for the environment the ensemble runs in.
ALLOWED_ROOTS: tuple[str, ...] = (os.path.realpath(os.path.expanduser("~")),)


def _validate_directory(directory: str) -> str:
    """Resolve and bound-check the directory. Raises ValueError if unusable or out of scope."""
    real = os.path.realpath(directory)
    if not os.path.isdir(real):
        raise ValueError(f"Not a directory: {directory!r}")
    if not any(real == root or real.startswith(root + os.sep) for root in ALLOWED_ROOTS):
        raise ValueError(f"Directory {directory!r} is outside the allowed roots")
    return real


def count_extensions(directory: str, extensions: list[str]) -> dict:
    """Walk `directory` read-only and count files by extension (case-insensitive)."""
    root = _validate_directory(directory)
    tally: dict[str, int] = {ext.lower(): 0 for ext in extensions}
    total = 0
    skipped: list[str] = []

    def _onerror(err: OSError) -> None:
        skipped.append(getattr(err, "filename", str(err)))

    # followlinks=False: never chase symlinks out of the tree.
    for _dirpath, _dirnames, filenames in os.walk(root, onerror=_onerror, followlinks=False):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in tally:
                tally[ext] += 1
                total += 1

    return {
        "directory": root,
        "counts": [{"extension": ext, "count": tally[ext.lower()]} for ext in extensions],
        "total_files": total,
        "skipped": skipped,
    }
