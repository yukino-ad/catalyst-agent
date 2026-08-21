from __future__ import annotations

import html
import re
from typing import Any


def literature_verification_level(paper: dict[str, Any]) -> str:
    """Classify traceability without treating API availability as science."""

    cross = paper.get("cross_verification", {})
    if not isinstance(cross, dict):
        cross = {}
    provider = str(paper.get("metadata_provider", "") or "").lower()
    crossref_verified = bool(
        cross.get("crossref_verified", False) is True
        or (
            paper.get("metadata_verified", False) is True
            and "crossref" in provider
        )
    )
    semantic_verified = bool(
        cross.get("semantic_scholar_verified", False) is True
        or (
            paper.get("metadata_verified", False) is True
            and "semantic" in provider
        )
    )
    trusted_single_source = bool(
        paper.get("metadata_verified", False) is True and provider
    )
    dual_source = bool(
        paper.get("cross_verified", False) is True
        or paper.get("kimi_cross_verified", False) is True
        or (crossref_verified and semantic_verified)
    )
    has_traceable_text = bool(
        (
            str(paper.get("doi", "") or "").strip()
            or str(paper.get("paper_id", "") or "").strip()
        )
        and str(paper.get("abstract", "") or "").strip()
    )
    if (
        dual_source
        and paper.get("metadata_verified", False) is True
        and has_traceable_text
    ):
        return "dual_source"
    if (
        crossref_verified or semantic_verified or trusted_single_source
    ) and has_traceable_text:
        return "single_source"
    return "unverified"


def paper_identities(paper: dict[str, Any]) -> set[str]:
    """Return stable identities used to exclude rejected papers."""

    identities: set[str] = set()
    doi = normalize_doi(paper.get("doi", ""))
    if doi:
        identities.add(f"doi:{doi}")
    openalex_id = normalize_openalex_id(paper.get("paper_id", ""))
    if openalex_id:
        identities.add(f"openalex:{openalex_id}")
    title = normalize_title(paper.get("title", ""))
    if title:
        identities.add(f"title:{title}")
    return identities


def normalize_doi(value: Any) -> str:
    doi = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip().rstrip(".")


def normalize_openalex_id(value: Any) -> str:
    paper_id = str(value or "").strip().lower()
    if paper_id.startswith("https://openalex.org/"):
        return paper_id.rsplit("/", 1)[-1]
    if paper_id.startswith("openalex:"):
        return paper_id.split(":", 1)[1]
    if re.fullmatch(r"w\d+", paper_id):
        return paper_id
    return ""


def normalize_title(value: Any) -> str:
    title = html.unescape(str(value or ""))
    title = re.sub(r"<[^>]+>", "", title).lower()
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", title)
    return " ".join(title.split())


def accepted_five_metal_sets(
    assertions: Any,
    task_analysis: dict[str, Any] | None = None,
    papers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build same-paper, explicit five-metal HEA evidence records."""

    if not isinstance(assertions, list):
        return []
    explicit = [
        item for item in assertions
        if isinstance(item, dict)
        and item.get("evidence_level") == "explicit"
        and not item.get("inferred", False)
    ]
    hea_papers = {
        str(item.get("paper_id", ""))
        for item in explicit
        if item.get("kind") == "material_family"
        and item.get("value") == "high_entropy_alloy"
    }
    task = task_analysis or {}
    paper_catalog = {
        str(paper.get("paper_id", "")): paper
        for paper in (papers or [])
        if isinstance(paper, dict)
    }
    required_reaction = str(task.get("reaction_family", "") or "").lower()
    reaction_papers = {
        str(item.get("paper_id", ""))
        for item in explicit
        if item.get("kind") == "reaction"
        and required_reaction
        and required_reaction in str(item.get("value", "")).lower()
    }
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for item in explicit:
        paper_id = str(item.get("paper_id", ""))
        values = item.get("value", [])
        if (
            item.get("kind") != "element_set"
            or paper_id not in hea_papers
            or not isinstance(values, list)
        ):
            continue
        elements = [str(value).strip() for value in values if str(value).strip()]
        if len(elements) != 5 or len(set(elements)) != 5:
            continue
        paper = paper_catalog.get(paper_id, {})
        verification_level = literature_verification_level(paper)
        quality = paper.get("evidence_quality", {})
        reaction_direct = (
            bool(quality.get("reaction_direct", False))
            if isinstance(quality, dict) and "reaction_direct" in quality
            else paper_id in reaction_papers
        )
        if required_reaction and not reaction_direct:
            continue
        key = (paper_id, tuple(sorted(elements)))
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "elements": elements,
            "element_count": 5,
            "assertion_id": item.get("assertion_id", ""),
            "evidence_id": item.get("evidence_id", ""),
            "paper_id": paper_id,
            "evidence": item.get("evidence", []),
            "explicit_high_entropy_identity": True,
            "same_paper_evidence": True,
            "reaction_evidence_accepted": (
                reaction_direct if required_reaction else True
            ),
            "reaction_assertion_required": False,
            "target_product_required": False,
            "human_accepted": True,
            "metadata_verified": bool(
                paper.get("metadata_verified", not paper_catalog)
            ),
            "metadata_provider": paper.get("metadata_provider", ""),
            "secondary_verification_pending": False,
            "requires_secondary_verification": False,
            "requires_human_confirmation": False,
            "evidence_use_mode": (
                "ideal_modeling_hypothesis"
                if verification_level == "unverified"
                else "reviewed_literature_evidence"
            ),
            "evidence_use_label": (
                "理想建模假设"
                if verification_level == "unverified"
                else "人工审查文献证据"
            ),
            "kimi_cross_verified": bool(
                paper.get("kimi_cross_verified", not paper_catalog)
            ),
            "eligible_for_c_stage": True,
        })
    return results
