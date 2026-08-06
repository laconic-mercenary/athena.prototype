"""Output contract for the recon committee."""

from __future__ import annotations

from pydantic import BaseModel


class DiscoveredPort(BaseModel):
    port: int
    protocol: str = "tcp"
    service: str
    version: str = ""
    notes: str = ""


class WebPath(BaseModel):
    path: str
    status_code: int
    size: int = 0


class CVECandidate(BaseModel):
    service: str
    version: str
    cve_id: str
    description: str
    exploit_available: bool = False


class ReconOutput(BaseModel):
    target: str
    discovered_target: str = ""    # target IP/host recovered from OSINT (git-leaked config)
    osint_sources: list[str] = []  # provenance: pages read, repo URL, leaking commit
    os_info: str = ""          # OS family/distro/version inferred from banners
    open_ports: list[DiscoveredPort]
    web_paths: list[WebPath] = []
    cve_candidates: list[CVECandidate] = []
    attack_surface_summary: str
    mitre_hypotheses: list[str] = []

    def render_full(self) -> str:
        lines = [f"Target: {self.target}"]
        if self.discovered_target and self.discovered_target != self.target:
            lines.append(f"Discovered via OSINT: {self.discovered_target}")
        if self.os_info:
            lines.append(f"Operating System: {self.os_info}")
        if self.osint_sources:
            lines.append("")
            lines.append("OSINT Sources:")
            for s in self.osint_sources:
                lines.append(f"  - {s}")
        lines.append("")
        lines.append("Open Ports:")
        for p in self.open_ports:
            ver = f" ({p.version})" if p.version else ""
            lines.append(f"  {p.port}/{p.protocol}  {p.service}{ver}")
        if self.web_paths:
            lines.append("")
            lines.append("Web Paths:")
            for wp in self.web_paths:
                lines.append(f"  {wp.status_code}  {wp.path}")
        if self.cve_candidates:
            lines.append("")
            lines.append("CVE Candidates:")
            for c in self.cve_candidates:
                exploitable = " [exploit available]" if c.exploit_available else ""
                lines.append(f"  {c.cve_id}  {c.service} {c.version}{exploitable}")
                lines.append(f"    {c.description}")
        lines.append("")
        lines.append("Attack Surface Summary:")
        lines.append(self.attack_surface_summary)
        if self.mitre_hypotheses:
            lines.append("")
            lines.append("MITRE ATT&CK Hypotheses: " + ", ".join(self.mitre_hypotheses))
        return "\n".join(lines)

    def render_digest(self) -> str:
        ports = ", ".join(f"{p.port}/{p.service}" for p in self.open_ports[:6])
        cves = ", ".join(c.cve_id for c in self.cve_candidates[:3])
        os_part = f"OS {self.os_info}; " if self.os_info else ""
        return (
            f"Target {self.target}: {os_part}{len(self.open_ports)} open ports [{ports}]; "
            f"{len(self.web_paths)} web paths; {len(self.cve_candidates)} CVE candidates"
            + (f" [{cves}]" if cves else "")
            + f"; MITRE: {', '.join(self.mitre_hypotheses[:4])}"
        )
