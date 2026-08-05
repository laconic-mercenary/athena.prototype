"""Serialise a LoadedEnsemble into a JSON-safe dict for the briefing tree."""

from __future__ import annotations

from athena.ensemble.types import LoadedEnsemble


def serialise_ensemble(ensemble: LoadedEnsemble) -> dict:
    committees = []
    for name, committee in ensemble.committees.items():
        elements = []
        for el in committee.elements:
            specialists = []
            for sp in el.specialists:
                skill_names = [
                    ensemble.skills[sid].name
                    for sid in sp.skill_ids
                    if sid in ensemble.skills
                ]
                specialists.append({
                    "id": sp.id,
                    "title": sp.title,
                    "skills": skill_names,
                })
            elements.append({
                "id": el.id,
                "label": el.label,
                "specialists": specialists,
            })
        committees.append({"name": name, "elements": elements})
    return {"committees": committees}
