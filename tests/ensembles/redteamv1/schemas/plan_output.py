"""Output contract for the planning committee."""

from __future__ import annotations

from pydantic import BaseModel


class AttackVector(BaseModel):
    id: str
    priority: int
    technique: str
    technique_name: str
    target_service: str
    exploit_description: str
    cve: str = ""
    success_criteria: str
    fallback: str = ""


class PlanOutput(BaseModel):
    primary_vector_id: str
    vectors: list[AttackVector]
    rationale: str
    mitre_chain: list[str]

    def render_full(self) -> str:
        lines = [
            f"Primary vector: {self.primary_vector_id}",
            f"Rationale: {self.rationale}",
            f"Kill chain: {' → '.join(self.mitre_chain)}",
            "",
            "Attack Vectors (ordered by priority):",
        ]
        for v in sorted(self.vectors, key=lambda x: x.priority):
            cve_note = f"  CVE: {v.cve}" if v.cve else ""
            lines += [
                f"",
                f"  [{v.id}] P{v.priority} — {v.technique} {v.technique_name}",
                f"  Target: {v.target_service}",
                f"  Exploit: {v.exploit_description}",
            ]
            if cve_note:
                lines.append(cve_note)
            lines += [
                f"  Success: {v.success_criteria}",
            ]
            if v.fallback:
                lines.append(f"  Fallback: {v.fallback}")
        return "\n".join(lines)

    def render_digest(self) -> str:
        primary = next((v for v in self.vectors if v.id == self.primary_vector_id), None)
        if primary:
            return (
                f"Primary: {primary.technique} against {primary.target_service} "
                f"({'CVE: ' + primary.cve if primary.cve else 'no specific CVE'}). "
                f"{len(self.vectors)} total vectors. Chain: {' → '.join(self.mitre_chain)}"
            )
        return f"{len(self.vectors)} attack vectors; chain: {' → '.join(self.mitre_chain)}"
