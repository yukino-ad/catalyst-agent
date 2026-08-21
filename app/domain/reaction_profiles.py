from __future__ import annotations

from copy import deepcopy
from typing import Any


REACTION_PROFILES: dict[str, dict[str, Any]] = {
    "CO2RR_CO": {
        "reaction_id": "CO2RR_CO",
        "reaction_family": "CO2RR",
        "display_name": "二氧化碳电还原生成一氧化碳",
        "target_product": "CO",
        "competing_reactions": ["HER"],
        "key_intermediates": ["CO2*", "COOH*", "CO*", "H*"],
        "descriptors": [
            "COOH* formation",
            "CO* adsorption",
            "H* adsorption",
        ],
        "tool_support": {
            "literature_rag": True,
            "candidate_generation": True,
            "fcc_bulk_modeling": True,
            "formation_energy_prediction": True,
            "reaction_activity_prediction": False,
        },
        "support_level": "full",
    },
    "CO2RR_HCOOH": {
        "reaction_id": "CO2RR_HCOOH",
        "reaction_family": "CO2RR",
        "display_name": "二氧化碳电还原生成甲酸或甲酸盐",
        "target_product": "HCOOH/HCOO-",
        "competing_reactions": ["HER", "CO2RR_CO"],
        "key_intermediates": ["CO2*", "OCHO*", "HCOO*", "H*"],
        "descriptors": ["OCHO* adsorption", "H* adsorption"],
        "tool_support": {
            "literature_rag": True,
            "candidate_generation": False,
            "fcc_bulk_modeling": True,
            "formation_energy_prediction": True,
            "reaction_activity_prediction": False,
        },
        "support_level": "partial",
    },
    "CO2RR_GENERAL": {
        "reaction_id": "CO2RR_GENERAL",
        "reaction_family": "CO2RR",
        "display_name": "二氧化碳电还原",
        "target_product": None,
        "competing_reactions": ["HER"],
        "key_intermediates": ["CO2*", "COOH*", "OCHO*", "CO*", "H*"],
        "descriptors": ["adsorption energy", "product selectivity"],
        "tool_support": {
            "literature_rag": True,
            "candidate_generation": False,
            "fcc_bulk_modeling": True,
            "formation_energy_prediction": True,
            "reaction_activity_prediction": False,
        },
        "support_level": "partial",
    },
    "HER": {
        "reaction_id": "HER",
        "reaction_family": "HER",
        "display_name": "析氢反应",
        "target_product": "H2",
        "competing_reactions": [],
        "key_intermediates": ["H*"],
        "descriptors": ["hydrogen adsorption free energy"],
        "tool_support": {
            "literature_rag": True,
            "candidate_generation": False,
            "fcc_bulk_modeling": True,
            "formation_energy_prediction": True,
            "reaction_activity_prediction": False,
        },
        "support_level": "literature_only",
    },
    "OER": {
        "reaction_id": "OER",
        "reaction_family": "OER",
        "display_name": "析氧反应",
        "target_product": "O2",
        "competing_reactions": [],
        "key_intermediates": ["OH*", "O*", "OOH*"],
        "descriptors": ["OH* adsorption", "O* adsorption", "OOH* adsorption"],
        "tool_support": {
            "literature_rag": True,
            "candidate_generation": True,
            "fcc_bulk_modeling": True,
            "formation_energy_prediction": True,
            "reaction_activity_prediction": False,
        },
        "support_level": "full",
    },
    "ORR": {
        "reaction_id": "ORR",
        "reaction_family": "ORR",
        "display_name": "氧还原反应",
        "target_product": "H2O/H2O2",
        "competing_reactions": [],
        "key_intermediates": ["O2*", "OOH*", "O*", "OH*"],
        "descriptors": ["OOH* adsorption", "OH* adsorption"],
        "tool_support": {
            "literature_rag": True,
            "candidate_generation": False,
            "fcc_bulk_modeling": False,
            "formation_energy_prediction": False,
            "reaction_activity_prediction": False,
        },
        "support_level": "literature_only",
    },
    "NRR": {
        "reaction_id": "NRR",
        "reaction_family": "NRR",
        "display_name": "电催化氮还原生成氨",
        "target_product": "NH3",
        "competing_reactions": ["HER"],
        "key_intermediates": ["N2*", "NNH*", "NH*", "NH2*"],
        "descriptors": ["N2 activation", "NNH* formation", "H* adsorption"],
        "tool_support": {
            "literature_rag": True,
            "candidate_generation": False,
            "fcc_bulk_modeling": False,
            "formation_energy_prediction": False,
            "reaction_activity_prediction": False,
        },
        "support_level": "literature_only",
    },
    "UNKNOWN": {
        "reaction_id": "UNKNOWN",
        "reaction_family": "UNKNOWN",
        "display_name": "尚未识别的科研任务",
        "target_product": None,
        "competing_reactions": [],
        "key_intermediates": [],
        "descriptors": [],
        "tool_support": {
            "literature_rag": True,
            "candidate_generation": False,
            "fcc_bulk_modeling": False,
            "formation_energy_prediction": False,
            "reaction_activity_prediction": False,
        },
        "support_level": "unsupported",
    },
}


C_STAGE_CAPABILITIES: dict[str, dict[str, Any]] = {
    "CO2RR_CO": {
        "candidate_generation": True,
        "evidence_policy": "exploratory_allowed",
        "allowed_material_families": ["high_entropy_alloy"],
        "scientific_scope": "fcc_high_entropy_metal_alloy",
    },
    "CO2RR_HCOOH": {
        "candidate_generation": True,
        "evidence_policy": "evidence_preferred",
        "allowed_material_families": ["high_entropy_alloy"],
        "scientific_scope": "fcc_high_entropy_metal_alloy",
    },
    "CO2RR_GENERAL": {
        "candidate_generation": True,
        "evidence_policy": "evidence_preferred",
        "allowed_material_families": ["high_entropy_alloy"],
        "scientific_scope": "fcc_high_entropy_metal_alloy",
    },
    "HER": {
        "candidate_generation": True,
        "evidence_policy": "evidence_preferred",
        "allowed_material_families": ["high_entropy_alloy"],
        "scientific_scope": "fcc_high_entropy_metal_alloy",
    },
    "ORR": {
        "candidate_generation": True,
        "evidence_policy": "evidence_preferred",
        "allowed_material_families": ["high_entropy_alloy"],
        "scientific_scope": "fcc_high_entropy_metal_alloy",
    },
    "OER": {
        "candidate_generation": True,
        "evidence_policy": "evidence_preferred",
        "allowed_material_families": ["high_entropy_alloy"],
        "scientific_scope": "fcc_high_entropy_metal_alloy",
    },
    "NRR": {
        "candidate_generation": True,
        "evidence_policy": "evidence_required",
        "allowed_material_families": ["high_entropy_alloy"],
        "scientific_scope": "fcc_high_entropy_metal_alloy",
        "special_warning": (
            "NRR candidates require strict contamination controls and "
            "reaction-specific validation."
        ),
    },
    "UNKNOWN": {
        "candidate_generation": False,
        "evidence_policy": "disabled",
        "allowed_material_families": [],
        "scientific_scope": "unsupported",
    },
}


for _reaction_id, _profile in REACTION_PROFILES.items():
    _profile["c_stage_capability"] = deepcopy(
        C_STAGE_CAPABILITIES.get(
            _reaction_id,
            C_STAGE_CAPABILITIES["UNKNOWN"],
        )
    )


def normalize_material_family(value: Any) -> str:
    """Map user- or LLM-facing material labels to internal identifiers."""

    raw = str(value or "").strip()
    normalized = raw.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "high_entropy_alloy",
        "high_entropy_catalyst",
        "hea",
        "高熵合金",
        "高熵催化剂",
        "高熵金属合金",
    }

    if raw in aliases or normalized in aliases:
        return "high_entropy_alloy"

    compact = normalized.replace("_", "")
    if (
        ("高熵" in raw and ("合金" in raw or "催化剂" in raw))
        or "highentropyalloy" in compact
        or "highentropycatalyst" in compact
    ):
        return "high_entropy_alloy"

    return normalized or "unspecified"


def resolve_c_stage_capability(
    task_analysis: dict[str, Any],
    accepted_papers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve whether a task may enter C-stage candidate design."""

    if not isinstance(task_analysis, dict):
        raise TypeError("task_analysis must be a dictionary")

    if accepted_papers is None:
        accepted_papers = []
    if not isinstance(accepted_papers, list):
        raise TypeError("accepted_papers must be a list")

    reaction_id = str(
        task_analysis.get("reaction_id", "UNKNOWN") or "UNKNOWN"
    ).strip()
    material_family_raw = str(
        task_analysis.get("material_family", "unspecified")
        or "unspecified"
    ).strip()
    material_family = normalize_material_family(material_family_raw)

    static = deepcopy(
        C_STAGE_CAPABILITIES.get(
            reaction_id,
            C_STAGE_CAPABILITIES["UNKNOWN"],
        )
    )

    accepted = [
        paper
        for paper in accepted_papers
        if isinstance(paper, dict)
        and paper.get("review_status") in {None, "", "accepted"}
    ]
    evidence_count = len(accepted)
    material_supported = (
        material_family in static["allowed_material_families"]
    )
    evidence_policy = static["evidence_policy"]
    warnings: list[str] = []

    if not static["candidate_generation"]:
        can_generate = False
        mode = "disabled"
        reason = "C-stage candidate generation is disabled."
    elif not material_supported:
        can_generate = False
        mode = "material_family_unsupported"
        reason = (
            "The current FCC generator only supports "
            "high_entropy_alloy tasks."
        )
    elif evidence_policy == "evidence_required" and evidence_count == 0:
        can_generate = False
        mode = "waiting_for_evidence"
        reason = (
            "Accepted reaction-specific literature is required before "
            "candidate generation."
        )
    elif evidence_count > 0:
        can_generate = True
        mode = "evidence_conditioned"
        reason = (
            "Candidates may be generated from accepted evidence and "
            "C1 constraints."
        )
    else:
        can_generate = True
        mode = "exploratory"
        reason = (
            "Candidates may be generated exploratorily, but no accepted "
            "reaction-specific evidence is available."
        )
        warnings.append(
            "Exploratory candidates satisfy composition and engineering "
            "rules only; reaction suitability is not established."
        )

    special_warning = static.get("special_warning")
    if special_warning:
        warnings.append(str(special_warning))

    return {
        "schema_version": "c-stage-capability-v1",
        "reaction_id": reaction_id,
        "material_family": material_family,
        "material_family_raw": material_family_raw,
        "accepted_evidence_count": evidence_count,
        "evidence_policy": evidence_policy,
        "generation_mode": mode,
        "can_generate_candidates": can_generate,
        "scientific_scope": static["scientific_scope"],
        "reaction_activity_prediction": False,
        "requires_human_confirmation": can_generate,
        "reason": reason,
        "warnings": warnings,
    }


def get_reaction_profile(reaction_id: str) -> dict[str, Any]:
    """返回档案副本，防止节点意外修改全局配置。"""
    profile = REACTION_PROFILES.get(reaction_id, REACTION_PROFILES["UNKNOWN"])
    return deepcopy(profile)


def detect_reaction_profile(question: str) -> dict[str, Any]:
    """在 LLM 不可用时，根据关键词识别反应。"""
    text = question.lower()
    if "析氧反应" in text:
        return get_reaction_profile("OER")

    if any(term in text for term in ("析氧", "oer", "oxygen evolution")):
        return get_reaction_profile("OER")

    if any(term in text for term in ("氧还原", "orr", "oxygen reduction")):
        return get_reaction_profile("ORR")

    if any(term in text for term in ("氮还原", "nrr", "nitrogen reduction", "合成氨")):
        return get_reaction_profile("NRR")

    if any(term in text for term in ("析氢", "her", "hydrogen evolution")):
        return get_reaction_profile("HER")

    is_co2rr = any(
        term in text
        for term in ("co2", "二氧化碳", "碳还原", "carbon dioxide reduction")
    )
    if is_co2rr:
        if any(term in text for term in ("甲酸", "甲酸盐", "formate", "hcooh")):
            return get_reaction_profile("CO2RR_HCOOH")
        if any(term in text for term in (
            "生成 co",
            "生成co",
            "制备 co",
            "制备co",
            "co选择性",
            "co 选择性",
            "选择性生成co",
            "选择性生成 co",
            "一氧化碳",
            "to co",
            "co selectivity",
            "carbon monoxide",
        )):
            return get_reaction_profile("CO2RR_CO")
        return get_reaction_profile("CO2RR_GENERAL")

    return get_reaction_profile("UNKNOWN")
