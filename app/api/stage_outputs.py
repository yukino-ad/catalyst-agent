from __future__ import annotations

from typing import Any


SAFE_SCALARS = (str, int, float, bool, type(None))
PREFERRED_KEYS = (
    "status",
    "reaction_id",
    "reaction_name",
    "material_family",
    "route",
    "router_mode",
    "candidate_count",
    "selected_count",
    "passed_count",
    "failed_count",
    "bundle_count",
    "job_count",
    "structure_count",
    "slab_count",
    "calculation_count",
    "approved_count",
    "rejected_count",
    "deferred_count",
    "formation_energy_ev_per_atom",
    "delta_percent",
    "omega",
    "next_stage",
)


DETAIL_FIELDS = (
    "candidate_id",
    "structure_id",
    "slab_id",
    "bundle_id",
    "adsorption_structure_id",
    "adsorbate",
    "site_id",
    "site_type",
    "elements",
    "composition",
    "formation_energy_ev_per_atom",
    "formation_energy_unit",
    "formation_energy_status",
    "delta_percent",
    "omega",
    "delta_pass",
    "omega_pass",
    "stability_decision",
    "quality_decision",
    "atom_count",
    "fixed_atom_count",
    "movable_atom_count",
    "measured_vacuum_angstrom",
)

DETAIL_LIST_KEYS: dict[str, tuple[str, ...]] = {
    "structure_modeling": ("bulk_structures", "structures"),
    "formation_energy": ("formation_energy_structures", "structures"),
    "stability_screening": ("stability_screened_structures", "structures"),
    "slab_generation": ("generated_slabs", "slabs"),
    "slab_quality": ("quality_passed_slabs", "slabs"),
    "adsorbate_structure_generation": ("adsorption_structures", "structures"),
    "adsorption_structure_quality": (
        "quality_passed_adsorption_structures",
        "quality_passed_structures",
        "structures",
    ),
    "adsorption_structure_review": (
        "adsorption_dft_approved_structures",
        "approved",
        "structures",
    ),
}


def safe_stage_outputs(output: Any, node_id: str = "") -> dict[str, Any]:
    """Return compact, JSON-safe stage facts without files, secrets, or arrays."""
    if not isinstance(output, dict):
        return {}
    result: dict[str, Any] = {}
    _collect(output, result)
    compact = dict(list(result.items())[:15])
    details = _stage_details(output, node_id)
    if details:
        compact["items"] = details
    return compact


def _collect(value: dict[str, Any], result: dict[str, Any]) -> None:
    for key in PREFERRED_KEYS:
        item = value.get(key)
        if isinstance(item, SAFE_SCALARS) and item not in ("", None):
            result.setdefault(key, item)
    for item in value.values():
        if isinstance(item, dict):
            _collect(item, result)


def _stage_details(output: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    keys = DETAIL_LIST_KEYS.get(node_id, ())
    if not keys:
        return []
    items = _find_first_list(output, keys)
    result: list[dict[str, Any]] = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        safe: dict[str, Any] = {}
        for key in DETAIL_FIELDS:
            value = item.get(key)
            if key == "formation_energy_ev_per_atom" and value is None:
                value = item.get("formation_energy")
            if isinstance(value, SAFE_SCALARS) or (
                isinstance(value, list)
                and all(isinstance(entry, SAFE_SCALARS) for entry in value)
            ) or (
                isinstance(value, dict)
                and all(isinstance(entry, SAFE_SCALARS) for entry in value.values())
            ):
                if value not in ("", None, [], {}):
                    safe[key] = value
        if "formation_energy_ev_per_atom" in safe:
            safe.setdefault(
                "formation_energy_unit",
                str(item.get("formation_energy_unit") or "eV/atom"),
            )
        if safe:
            result.append(safe)
    return result


def _find_first_list(value: Any, keys: tuple[str, ...]) -> list[Any]:
    if not isinstance(value, dict):
        return []
    for key in keys:
        item = value.get(key)
        if isinstance(item, list):
            return item
    for item in value.values():
        found = _find_first_list(item, keys)
        if found:
            return found
    return []
