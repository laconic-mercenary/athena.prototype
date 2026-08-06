"""Skills: OS fingerprinting, split by OS family.

Each tool runs nmap under the hood against the ports characteristic of one OS family, so the
fingerprinting reads as a deliberate per-family probe (unix vs Windows NT vs Windows remote
services) rather than one generic scan. nmap -O (OS detection) needs root and is unavailable,
so these infer the family from open ports + service banners.
"""

from __future__ import annotations

import re
import subprocess

_PORT_RE = re.compile(r"^(\d+)/(tcp|udp)\s+open\s+(\S+)(?:\s+(.+))?$", re.MULTILINE)


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


def _run_nmap(target: str, ports: str) -> dict:
    cmd = ["nmap", "-sV", "-T4", "-p", ports, target]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return {"error": "nmap not found — install nmap on the harness machine", "stdout": "", "open_ports": []}
    except subprocess.TimeoutExpired:
        return {"error": "nmap timed out after 120s", "stdout": "", "open_ports": []}
    return {
        "stdout": result.stdout,
        "returncode": result.returncode,
        "open_ports": _parse_ports(result.stdout),
    }


def unix_type_check(target: str) -> dict:
    """Probe Unix/Linux indicators — SSH and common Linux-served HTTP."""
    ports = "22,80,443"
    res = _run_nmap(target, ports)
    open_ports = res.get("open_ports", [])
    services = " ".join(f"{p['service']} {p['version']}" for p in open_ports).lower()
    linux_hint = any(k in services for k in ("openssh", "ubuntu", "debian", "werkzeug", "nginx", "apache"))
    return {
        "check": "unix_type_check",
        "family": "unix/linux",
        "target": target,
        "ports_scanned": ports,
        "open_ports": open_ports,
        "signal": (
            "Unix/Linux indicators present (SSH or Linux-served HTTP banners)."
            if linux_hint else
            "No decisive Unix banner on these ports."
        ),
        "stdout": res.get("stdout", ""),
        "error": res.get("error"),
    }


def windows_smb_check(target: str) -> dict:
    """Probe Windows file/RPC indicators — SMB / RPC / NetBIOS."""
    ports = "135,139,445"
    res = _run_nmap(target, ports)
    open_ports = res.get("open_ports", [])
    return {
        "check": "windows_smb_check",
        "family": "windows-smb (smb/rpc/netbios)",
        "target": target,
        "ports_scanned": ports,
        "open_ports": open_ports,
        "signal": (
            "SMB/RPC/NetBIOS open — host is likely Windows."
            if open_ports else
            "No SMB/RPC/NetBIOS services — host does not present as Windows on these ports."
        ),
        "stdout": res.get("stdout", ""),
        "error": res.get("error"),
    }


def windows_rdp_check(target: str) -> dict:
    """Probe Windows remote-service indicators — RDP / WinRM."""
    ports = "3389,5985"
    res = _run_nmap(target, ports)
    open_ports = res.get("open_ports", [])
    return {
        "check": "windows_rdp_check",
        "family": "windows-remote (rdp/winrm)",
        "target": target,
        "ports_scanned": ports,
        "open_ports": open_ports,
        "signal": (
            "RDP/WinRM open — host is likely Windows."
            if open_ports else
            "No RDP/WinRM services — no Windows remote-management surface on these ports."
        ),
        "stdout": res.get("stdout", ""),
        "error": res.get("error"),
    }
