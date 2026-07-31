"""Skill: searchsploit — ExploitDB CVE/exploit lookup."""

from __future__ import annotations

import json
import re
import subprocess


def searchsploit(query: str) -> dict:
    try:
        result = subprocess.run(
            ["searchsploit", "--json", query],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return {
            "query": query,
            "results": [],
            "note": (
                "searchsploit is not installed on this machine. "
                "Reason from your CVE knowledge for: " + query
            ),
        }
    except subprocess.TimeoutExpired:
        return {"query": query, "results": [], "error": "searchsploit timed out"}

    try:
        data = json.loads(result.stdout)
        exploits = data.get("RESULTS_EXPLOIT", [])
        results = [
            {
                "title": e.get("Title", ""),
                "path": e.get("Path", ""),
                "cve": _extract_cve(e.get("Title", "")),
            }
            for e in exploits[:20]
        ]
        return {"query": query, "results": results, "total": len(exploits)}
    except (json.JSONDecodeError, KeyError):
        return {
            "query": query,
            "results": [],
            "raw": result.stdout[:1000],
            "error": "Could not parse searchsploit JSON output",
        }


_CVE_RE = re.compile(r"CVE-\d{4}-\d+", re.IGNORECASE)


def _extract_cve(title: str) -> str:
    m = _CVE_RE.search(title)
    return m.group(0).upper() if m else ""
