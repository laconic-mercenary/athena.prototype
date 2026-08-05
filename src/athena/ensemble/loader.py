"""Ensemble loader.

Reads a manifest.yml from an ensemble root directory and produces a
LoadedEnsemble — all file references followed, schemas imported, skill
impls imported. Raises ValueError with a descriptive message on any
resolution failure so broken manifests are caught at load time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml

from athena.ensemble.types import (
    LoadedCommittee,
    LoadedElement,
    LoadedEnsemble,
    LoadedSkill,
    LoadedSpecialist,
    WorkflowNode,
    WorkflowTransition,
)


# ---------------------------------------------------------------------------
# Skill helpers
# ---------------------------------------------------------------------------

def _params_to_json_schema(params: dict) -> dict:
    """Convert a skill.yml parameters block to a JSON Schema object."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, p in params.items():
        raw_type = p.get("type", "string")
        prop: dict[str, Any] = {"type": raw_type}
        if "description" in p:
            prop["description"] = p["description"]
        if raw_type == "array" and "items" not in p:
            prop["items"] = {"type": "string"}
        properties[name] = prop
        if p.get("required", True):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _load_skill_impl(impl_spec: str, ensemble_root: Path):
    """Load a skill callable from "relative/path/impl.py::func_name"."""
    if "::" not in impl_spec:
        raise ValueError(f"Invalid impl spec {impl_spec!r} — expected 'path::func'")
    rel_path, func_name = impl_spec.split("::", 1)
    impl_path = ensemble_root / rel_path
    if not impl_path.exists():
        raise ValueError(f"Skill impl not found: {impl_path}")
    module_name = f"_ensemble_skill_{impl_path.stem}_{id(impl_path)}"
    spec = importlib.util.spec_from_file_location(module_name, impl_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load module from {impl_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    if not hasattr(module, func_name):
        raise ValueError(f"Function {func_name!r} not found in {impl_path}")
    return getattr(module, func_name)


def _load_skill(skill_entry: dict, ensemble_root: Path) -> LoadedSkill:
    skill_id = skill_entry["id"]
    def_path = ensemble_root / skill_entry["definition"]
    if not def_path.exists():
        raise ValueError(f"Skill definition not found: {def_path}")
    raw = yaml.safe_load(def_path.read_text())
    impl = _load_skill_impl(skill_entry["impl"], ensemble_root)
    return LoadedSkill(
        id=skill_id,
        name=raw["name"],
        description=raw.get("description", ""),
        parameters=_params_to_json_schema(raw.get("parameters", {})),
        impl=impl,
        side_effect=raw.get("side_effect", "reads_local"),
    )


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _load_schemas_package(ensemble_root: Path):
    """Import the ensemble's schemas/ package and return the module."""
    schemas_dir = ensemble_root / "schemas"
    init_path = schemas_dir / "__init__.py"
    if not init_path.exists():
        raise ValueError(f"Missing schemas/__init__.py in {ensemble_root}")
    pkg_name = f"_ensemble_schemas_{ensemble_root.name}_{id(ensemble_root)}"
    spec = importlib.util.spec_from_file_location(
        pkg_name,
        init_path,
        submodule_search_locations=[str(schemas_dir)],
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load schemas package from {schemas_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _resolve_schema(schemas_module, ref: str):
    """Resolve 'schemas.ClassName' to the actual class."""
    if not ref.startswith("schemas."):
        raise ValueError(f"output_schema must be 'schemas.<ClassName>', got {ref!r}")
    class_name = ref[len("schemas."):]
    klass = getattr(schemas_module, class_name, None)
    if klass is None:
        raise ValueError(f"Schema class {class_name!r} not found in schemas/__init__.py")
    return klass


# ---------------------------------------------------------------------------
# Specialist / element helpers
# ---------------------------------------------------------------------------

def _load_specialist(
    yml_path: Path,
    element_model: str | None,
    element_provider: str | None,
    committee_model: str,
    committee_provider: str,
    global_default_model: str,
    global_provider: str,
    element_skill_ids: list[str],
) -> LoadedSpecialist:
    if not yml_path.exists():
        raise ValueError(f"Specialist yml not found: {yml_path}")
    raw = yaml.safe_load(yml_path.read_text())
    # Model cascade: specialist yml → element override → committee → global default
    model = raw.get("model") or element_model or committee_model or global_default_model
    provider = raw.get("provider") or element_provider or committee_provider or global_provider
    temperature_raw = raw.get("temperature")
    temperature = float(temperature_raw) if temperature_raw is not None else None
    max_tokens_raw = raw.get("max_tokens")
    max_tokens = int(max_tokens_raw) if max_tokens_raw is not None else None
    # Specialist-level skills override the element's list; element list is the fallback.
    skill_ids = raw.get("skills", element_skill_ids)
    stem = yml_path.stem
    return LoadedSpecialist(
        id=stem,
        title=raw.get("title") or stem,
        system=raw.get("system", ""),
        model=model,
        provider=provider,
        temperature=temperature,
        skill_ids=skill_ids,
        max_tokens=max_tokens,
        base_url=raw.get("ollama_base_url"),
        auth_headers_env=raw.get("auth_headers_env"),
    )


def _load_element(
    element_raw: dict,
    committee_dir: Path,
    committee_model: str,
    committee_provider: str,
    global_default_model: str,
    global_provider: str,
) -> LoadedElement:
    element_id = element_raw["id"]
    label = element_raw.get("label", element_id)
    instances = element_raw.get("instances", 1)
    skill_ids = element_raw.get("skills", [])
    # Element-level model/provider override slots between committee and specialist in the cascade.
    element_model: str | None = element_raw.get("model") or None
    element_provider: str | None = element_raw.get("provider") or None
    specialists = [
        _load_specialist(
            committee_dir / spec_path,
            element_model,
            element_provider,
            committee_model,
            committee_provider,
            global_default_model,
            global_provider,
            element_skill_ids=skill_ids,
        )
        for spec_path in element_raw.get("specialists", [])
    ]
    if not specialists:
        raise ValueError(f"Element {element_id!r} has no specialists")
    return LoadedElement(
        id=element_id,
        label=label,
        instances=instances,
        specialists=specialists,
        skill_ids=skill_ids,
        max_tool_calls=int(element_raw.get("max_tool_calls", 1)),
    )


# ---------------------------------------------------------------------------
# Committee helpers
# ---------------------------------------------------------------------------

def _load_committee(
    name: str,
    committee_raw: dict,
    committees_dir: Path,
    schemas_module,
    global_default_model: str,
    global_provider: str,
) -> LoadedCommittee:
    committee_dir = committees_dir / name
    model = committee_raw.get("model") or global_default_model
    provider = committee_raw.get("provider") or global_provider
    max_steps = int(committee_raw.get("max_steps", 12))

    leader_path = committees_dir / committee_raw["leader"]
    if not leader_path.exists():
        raise ValueError(f"Leader yml not found: {leader_path}")
    leader_raw = yaml.safe_load(leader_path.read_text())
    leader_system = leader_raw.get("system", "")

    playbook_path = committee_dir / "playbook.md"
    playbook = playbook_path.read_text() if playbook_path.exists() else ""

    elements = [
        _load_element(
            e,
            committee_dir,
            model,
            provider,
            global_default_model,
            global_provider,
        )
        for e in committee_raw.get("elements", [])
    ]

    task_cards: dict[str, str] = {}
    for element in elements:
        task_md = committee_dir / "elements" / element.id / "task.md"
        if task_md.exists():
            task_cards[element.id] = task_md.read_text()

    output_schema_ref = ""  # populated from workflow node
    consumes_raw = committee_raw.get("consumes", {})

    return LoadedCommittee(
        name=name,
        leader_system=leader_system,
        model=model,
        provider=provider,
        max_steps=max_steps,
        playbook=playbook,
        elements=elements,
        task_cards=task_cards,
        output_schema=object,  # patched after workflow is parsed
        consumes_required=consumes_raw.get("required", []),
        consumes_optional=consumes_raw.get("optional", []),
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def load_ensemble(path: Path) -> LoadedEnsemble:
    """Load an ensemble from a directory containing manifest.yml."""
    manifest_path = path / "manifest.yml"
    if not manifest_path.exists():
        raise ValueError(f"No manifest.yml found in {path}")

    raw = yaml.safe_load(manifest_path.read_text())
    name = raw["name"]
    version = str(raw["version"])
    description = raw.get("description", "")

    capability_path = path / raw.get("capability_doc", "capability.md")
    if not capability_path.exists():
        raise ValueError(f"capability_doc not found: {capability_path}")
    capability = capability_path.read_text()

    schemas_module = _load_schemas_package(path)

    # Skills registry
    skills: dict[str, LoadedSkill] = {}
    for skill_entry in raw.get("skills", []):
        skill = _load_skill(skill_entry, path)
        skills[skill.id] = skill

    # Global defaults (not declared in the manifest for inventory; use sensible defaults)
    global_default_model = "claude-sonnet-4-6"
    global_provider = "anthropic"

    # Committees
    committees_dir = path / "committees"
    committees_raw = raw.get("committees", {})
    committees: dict[str, LoadedCommittee] = {}
    for committee_name, committee_raw in committees_raw.items():
        committees[committee_name] = _load_committee(
            name=committee_name,
            committee_raw=committee_raw,
            committees_dir=committees_dir,
            schemas_module=schemas_module,
            global_default_model=global_default_model,
            global_provider=global_provider,
        )

    # Workflow graph
    workflow_raw = raw.get("workflow", {})
    entry = workflow_raw["entry"]
    nodes_raw = workflow_raw.get("nodes", {})
    workflow: dict[str, WorkflowNode] = {}

    for node_name, node_raw in nodes_raw.items():
        schema_ref = node_raw.get("output_schema", "")
        output_schema = _resolve_schema(schemas_module, schema_ref)

        # Patch the output_schema onto the already-loaded committee
        if node_name in committees:
            committees[node_name].output_schema = output_schema

        transitions = [
            WorkflowTransition(
                to=t["to"],
                condition=t.get("condition") or None,
            )
            for t in node_raw.get("transitions", [])
        ]
        workflow[node_name] = WorkflowNode(
            name=node_name,
            transitions=transitions,
            output_schema=output_schema,
        )

    # Validate: every committee referenced in the workflow exists
    for node_name in workflow:
        if node_name not in committees:
            raise ValueError(f"Workflow node {node_name!r} has no matching committee definition")

    # Validate: every skill_id referenced by elements or specialists exists
    for committee in committees.values():
        for element in committee.elements:
            for sid in element.skill_ids:
                if sid not in skills:
                    raise ValueError(
                        f"Element {element.id!r} in committee {committee.name!r} "
                        f"references unknown skill {sid!r}"
                    )
            for specialist in element.specialists:
                for sid in specialist.skill_ids:
                    if sid not in skills:
                        raise ValueError(
                            f"Specialist {specialist.id!r} in element {element.id!r} "
                            f"references unknown skill {sid!r}"
                        )

    return LoadedEnsemble(
        name=name,
        version=version,
        description=description,
        capability=capability,
        entry=entry,
        workflow=workflow,
        committees=committees,
        skills=skills,
        root=path,
    )
