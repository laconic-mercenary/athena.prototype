"""Skill: nmap_scan — run nmap and parse open ports."""

from __future__ import annotations

import re
import subprocess


def nmap_scan(
    target: str,
    ports: str = "1-1000",
    flags: str = "-sV -sC -T4",
) -> dict:
    cmd = ["nmap"] + flags.split() + ["-p", ports, target]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
    except FileNotFoundError:
        return {"error": "nmap not found — install nmap on the harness machine", "stdout": "", "open_ports": []}
    except subprocess.TimeoutExpired:
        return {"error": "nmap timed out after 300s", "stdout": "", "open_ports": []}

    open_ports = _parse_ports(result.stdout)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr[:500] if result.stderr else "",
        "returncode": result.returncode,
        "open_ports": open_ports,
    }


_PORT_RE = re.compile(
    r"^(\d+)/(tcp|udp)\s+open\s+(\S+)(?:\s+(.+))?$", re.MULTILINE
)


def _parse_ports(output: str) -> list[dict]:
    ports = []
    for m in _PORT_RE.finditer(output):
        ports.append({
            "port": int(m.group(1)),
            "protocol": m.group(2),
            "service": m.group(3),
            "version": (m.group(4) or "").strip(),
        })
    return ports
