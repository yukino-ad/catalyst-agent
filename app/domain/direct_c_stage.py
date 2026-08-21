from __future__ import annotations

import re
from typing import Any

from app.domain.candidate_constraints import MODEL_SUPPORTED_ELEMENTS
from app.domain.llm_validation import strict_bool


MODELING_TERMS = (
    "\u6784\u9020", "\u6784\u5efa", "\u5efa\u6a21", "\u751f\u6210\u7ed3\u6784",
    "build", "construct", "model",
)
HEA_TERMS = (
    "\u9ad8\u71b5", "\u9ad8\u71b5\u5408\u91d1", "\u9ad8\u71b5\u50ac\u5316\u5242",
    "high entropy alloy", "high-entropy alloy", "hea",
)
NEGATED_MODELING_TERMS = (
    "\u4e0d\u5efa\u6a21", "\u4e0d\u8981\u5efa\u6a21", "\u4e0d\u7ee7\u7eed\u5efa\u6a21",
    "do not model", "without modeling",
)


def classify_direct_c_stage_request(
    question: str,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recognize an explicit request to model one exact five-metal HEA."""

    text = str(question or "").strip()
    lower = text.lower()
    analysis = analysis if isinstance(analysis, dict) else {}
    elements = _extract_supported_elements(text)
    llm_flags = []
    for field in ("explicit_hea_modeling_request", "needs_structure_modeling"):
        if field in analysis:
            try:
                llm_flags.append(strict_bool(analysis[field], field=field))
            except TypeError:
                llm_flags.append(False)
    llm_requested = any(llm_flags)
    llm_elements = _normalize_elements(analysis.get("specified_elements", []))
    if len(elements) != 5 and len(llm_elements) == 5:
        elements = llm_elements

    has_modeling_action = any(term in lower for term in MODELING_TERMS)
    has_hea_identity = any(term in lower for term in HEA_TERMS)
    negated = any(term in lower for term in NEGATED_MODELING_TERMS)
    requested = bool(
        not negated
        and has_modeling_action
        and has_hea_identity
        and len(elements) == 5
        and (llm_requested or analysis.get("analysis_mode") != "llm")
    )
    return {
        "schema_version": "a-direct-c-v1",
        "requested": requested,
        "direct_c_stage_requested": requested,
        "reason": (
            "explicit_five_metal_hea_modeling_request"
            if requested else "normal_a_b_c_workflow"
        ),
        "specified_elements": elements if requested else [],
        "element_count": len(elements) if requested else 0,
        "material_family": "high_entropy_alloy" if requested else "",
        "needs_candidate_design": False,
        "needs_structure_modeling": requested,
        "fixed_composition_sampling": requested,
        "structure_variant_count": 3 if requested else 0,
        "scientific_scope": (
            "reaction_agnostic_bulk_stability" if requested else ""
        ),
        "skip_literature_stage": requested,
        "classification_source": (
            "llm_validated" if requested and llm_requested
            else "deterministic_fallback" if requested
            else "not_applicable"
        ),
        "llm_requested": llm_requested,
    }


def _extract_supported_elements(text: str) -> list[str]:
    # Remove stage labels and paths before looking for explicit chemistry.
    cleaned = re.sub(r"\bC\d+(?:\.\d+)*\b", " ", str(text))
    cleaned = re.sub(r"[A-Za-z]:\\[^\r\n\"']+", " ", cleaned)
    symbols = sorted(MODEL_SUPPORTED_ELEMENTS, key=len, reverse=True)
    symbol_pattern = "|".join(map(re.escape, symbols))

    result: list[str] = []
    # Treat a contiguous formula as one composition. Do not accept a
    # six-element formula by taking its first five symbols.
    for formula in re.findall(
        rf"(?<![A-Za-z])(?:{symbol_pattern})+(?![a-z])",
        cleaned,
    ):
        tokens = re.findall(symbol_pattern, formula)
        normalized = _normalize_elements(tokens)
        if len(normalized) == 5 and len(tokens) == 5:
            result.extend(normalized)

    separated = re.findall(
        rf"(?<![A-Za-z0-9])(?:{symbol_pattern})(?![A-Za-z0-9])",
        cleaned,
    )
    result.extend(separated)
    return _normalize_elements(result)


def _normalize_elements(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    supported = set(MODEL_SUPPORTED_ELEMENTS)
    result: list[str] = []
    for value in values:
        element = str(value or "").strip()
        if element in supported and element not in result:
            result.append(element)
    return result
