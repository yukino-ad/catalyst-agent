from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.domain.reaction_profiles import (
    detect_reaction_profile,
    get_reaction_profile,
    normalize_material_family,
)


REACTION_QUERY_TERMS = {
    "CO2RR": [
        "CO2 electroreduction",
        "electrochemical carbon dioxide reduction",
    ],
    "HER": ["hydrogen evolution reaction", "HER electrocatalysis"],
    "OER": ["oxygen evolution reaction", "OER electrocatalysis"],
    "ORR": ["oxygen reduction reaction", "ORR electrocatalysis"],
    "NRR": ["nitrogen reduction reaction", "NRR electrocatalysis"],
}

PRODUCT_QUERY_TERMS = {
    "CO": ["carbon monoxide", "CO selectivity", "CO formation"],
    "HCOOH/HCOO-": ["formic acid", "formate selectivity"],
    "H2": ["hydrogen production"],
    "O2": ["oxygen production"],
    "NH3": ["ammonia production"],
}

MATERIAL_QUERY_TERMS = {
    "high_entropy_alloy": [
        "high entropy alloy",
        "five-component alloy",
        "multimetallic electrocatalyst",
    ],
}


class TaskContextBuilder:
    """Validate LLM task analysis and build one A-to-B search contract."""

    def build(
        self,
        question: str,
        analysis: dict[str, Any],
        user_overrides: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(analysis, dict):
            raise TypeError("analysis must be a dictionary")

        question = str(question or "").strip()
        if not question:
            raise ValueError("question must not be empty")

        user_overrides = user_overrides or {}
        rule_profile = detect_reaction_profile(question)
        llm_reaction_id = str(
            analysis.get("reaction_id", "UNKNOWN") or "UNKNOWN"
        ).strip()
        reaction_id = self._resolve_reaction_id(
            llm_reaction_id,
            rule_profile["reaction_id"],
        )
        profile = get_reaction_profile(reaction_id)

        corrections: list[dict[str, Any]] = []
        if reaction_id != llm_reaction_id:
            corrections.append({
                "field": "reaction_id",
                "llm_value": llm_reaction_id,
                "final_value": reaction_id,
                "reason": "explicit reaction or product wording",
            })

        target_product = profile.get("target_product")
        llm_product = analysis.get("target_product")
        if target_product is None and llm_product:
            target_product = str(llm_product).strip() or None
        if target_product != llm_product and target_product is not None:
            corrections.append({
                "field": "target_product",
                "llm_value": llm_product,
                "final_value": target_product,
                "reason": "validated Reaction Profile target",
            })

        material_family = normalize_material_family(
            analysis.get("material_family", "unspecified")
        )
        if self._mentions_hea(question):
            material_family = "high_entropy_alloy"

        online_preference = self._online_preference(question)
        needs_candidate_design = self._needs_candidate_design(
            question,
            analysis,
            user_overrides,
        )
        needs_structure_modeling = self._needs_structure_modeling(
            question,
        )
        needs_property_prediction = self._needs_property_prediction(question)
        needs_dft = self._needs_dft(question)
        requested_scope = (
            "candidate_only"
            if needs_candidate_design and not any((
                needs_structure_modeling,
                needs_property_prediction,
                needs_dft,
            ))
            else "full_workflow"
            if any((
                needs_structure_modeling,
                needs_property_prediction,
                needs_dft,
            ))
            else "literature_only"
        )

        unresolved_fields: list[str] = []
        if reaction_id == "UNKNOWN":
            unresolved_fields.append("reaction_family")
        if reaction_id == "CO2RR_GENERAL" and not target_product:
            unresolved_fields.append("target_product")
        if material_family in {"", "unspecified"}:
            unresolved_fields.append("material_family")

        confidence_by_field = {
            "reaction_family": self._confidence(
                reaction_id != "UNKNOWN",
                rule_profile["reaction_id"] != "UNKNOWN",
            ),
            "target_product": self._confidence(
                target_product is not None,
                rule_profile.get("target_product") is not None,
            ),
            "material_family": self._confidence(
                material_family not in {"", "unspecified"},
                self._mentions_hea(question),
            ),
        }

        evidence_requirements = self._evidence_requirements(
            reaction_id,
            target_product,
            material_family,
            needs_candidate_design,
        )
        query_terms = self._query_terms(
            profile["reaction_family"],
            target_product,
            material_family,
            needs_candidate_design,
        )
        search_query = " ".join(query_terms)

        context = {
            "schema_version": "a1.1",
            "original_question": question,
            "understanding_status": (
                "complete" if not unresolved_fields else "partial"
            ),
            "reaction_id": reaction_id,
            "reaction_family": profile["reaction_family"],
            "target_product": target_product,
            "material_family": material_family,
            "element_count": 5 if self._mentions_five(question) else None,
            "crystal_structure": "FCC" if "fcc" in question.lower() else None,
            "requested_scope": requested_scope,
            "online_preference": online_preference,
            "needs_candidate_design": needs_candidate_design,
            "needs_structure_modeling": needs_structure_modeling,
            "needs_property_prediction": needs_property_prediction,
            "needs_dft": needs_dft,
            "explicit_requested_actions": {
                "candidate_design": needs_candidate_design,
                "structure_modeling": needs_structure_modeling,
                "property_prediction": needs_property_prediction,
                "dft": needs_dft,
            },
            "recommended_next_actions": self._recommended_next_actions(),
            "evidence_requirements": evidence_requirements,
            "unresolved_fields": unresolved_fields,
            "requires_clarification": reaction_id == "UNKNOWN",
            "clarification_question": (
                "请确认目标电催化反应，例如 CO2RR、HER、OER、ORR 或 NRR。"
                if reaction_id == "UNKNOWN"
                else ""
            ),
            "confidence_by_field": confidence_by_field,
            "query_terms": query_terms,
            "search_query": search_query,
        }
        validation = {
            "schema_version": "a1.1-validation",
            "status": "validated",
            "corrections": corrections,
            "unresolved_fields": unresolved_fields,
            "llm_raw": deepcopy(analysis),
        }
        return context, validation

    @staticmethod
    def apply_to_analysis(
        analysis: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(analysis)
        for field in (
            "reaction_id",
            "reaction_family",
            "target_product",
            "material_family",
            "needs_candidate_design",
            "needs_structure_modeling",
            "needs_property_prediction",
            "needs_dft",
        ):
            result[field] = context.get(field)
        result["reaction_profile"] = get_reaction_profile(
            context.get("reaction_id", "UNKNOWN")
        )
        result["canonical_context_schema"] = context.get("schema_version")
        result["analysis_mode"] = (
            "llm_validated"
            if analysis.get("analysis_mode") == "llm"
            else analysis.get("analysis_mode", "rule_fallback")
        )
        return result

    @staticmethod
    def _resolve_reaction_id(llm_value: str, rule_value: str) -> str:
        if rule_value != "UNKNOWN":
            return rule_value
        # Without an explicit reaction clue in the user's text, a model guess
        # must not silently select a scientific workflow.
        return "UNKNOWN"

    @staticmethod
    def _mentions_hea(question: str) -> bool:
        text = question.lower()
        return any(term in text for term in (
            "高熵", "high entropy", "hea", "五元", "five-component",
        ))

    @staticmethod
    def _mentions_five(question: str) -> bool:
        text = question.lower()
        return any(term in text for term in (
            "五元", "五种金属", "5种金属", "five-component", "five element",
        ))

    @staticmethod
    def _online_preference(question: str) -> str:
        text = question.lower()
        if any(term in text for term in (
            "不联网", "不要联网", "只用本地", "仅使用本地",
            "offline only", "local only",
        )):
            return "forbidden"
        if any(term in text for term in (
            "仅在本地证据不足时", "本地证据不足时联网", "本地不足时联网",
            "按需联网", "必要时联网", "少量联网补充",
            "online if needed", "online when local evidence is insufficient",
        )):
            return "auto"
        if any(term in text for term in (
            "必须联网", "一定联网", "强制联网", "必须在线检索",
            "最新文献", "最新研究", "最新进展",
            "required online search", "latest literature", "recent studies",
        )):
            return "required"
        return "auto"

    @staticmethod
    def _needs_candidate_design(
        question: str,
        analysis: dict[str, Any],
        overrides: dict[str, Any],
    ) -> bool:
        text = question.lower()
        # Only validated JSON booleans may control the workflow.
        requested = analysis.get("needs_candidate_design", False) is True
        requested = requested or any(term in text for term in (
            "设计", "候选", "推荐", "筛选", "组合",
            "design", "candidate", "recommend", "screen",
        ))
        return requested or bool(overrides.get("required_elements"))

    @staticmethod
    def _needs_structure_modeling(
        question: str,
    ) -> bool:
        text = question.lower()
        if any(term in text for term in (
            "不要进行fcc结构建模", "不进行fcc结构建模",
            "不要进行结构建模", "不进行结构建模",
            "不继续结构建模", "本次不继续结构建模",
            "do not perform structure modeling",
        )):
            return False
        if any(term in text for term in (
            "不继续建模", "不要建模", "只输出候选", "仅输出候选",
        )):
            return False
        if any(term in text for term in (
            "建模", "生成结构", "晶体结构", "fcc结构", "fcc 建模",
        )):
            return True
        if any(term in text for term in (
            "不继续建模", "不要建模", "只输出候选", "仅输出候选",
            "candidate only", "do not model",
        )):
            return False
        return any(
            term in text for term in (
                "建模", "生成结构", "cif", "poscar", "structure modeling",
            )
        )

    @staticmethod
    def _needs_property_prediction(question: str) -> bool:
        text = question.lower()
        if any(term in text for term in (
            "不要进行形成能预测", "不进行形成能预测",
            "不要进行性质预测", "不进行性质预测",
            "不要进行稳定性计算", "不进行稳定性计算",
            "do not perform property prediction",
        )):
            return False
        return any(term in text for term in (
            "性质预测", "稳定性预测", "稳定性筛选", "形成能预测",
            "cgcnn", "property prediction", "stability screening",
            "formation energy prediction",
        ))

    @staticmethod
    def _needs_dft(question: str) -> bool:
        text = question.lower()
        if any(term in text for term in (
            "不要进行dft", "不进行dft", "不要进行vasp",
            "不进行vasp", "不要进行dft计算", "不进行dft计算",
            "do not perform dft", "no dft calculation",
        )):
            return False
        return any(term in text for term in (
            "dft", "密度泛函", "第一性原理", "vasp计算", "vasp 计算",
            "提交超算", "density functional", "first-principles",
        ))

    @staticmethod
    def _recommended_next_actions() -> list[dict[str, Any]]:
        return [
            {
                "action": "fcc_modeling",
                "recommended": True,
                "reason": (
                    "FCC is a common practical starting structure for "
                    "metallic high-entropy-alloy modeling."
                ),
            },
            {
                "action": "property_prediction",
                "recommended": True,
                "reason": (
                    "Formation-energy and delta/Omega screening provide a "
                    "lower-cost theoretical prescreen before DFT."
                ),
            },
            {
                "action": "dft_validation",
                "recommended": True,
                "reason": (
                    "DFT provides higher-fidelity theoretical validation but "
                    "requires more compute and may require a cluster."
                ),
            },
        ]

    @staticmethod
    def _confidence(known: bool, explicit: bool) -> float:
        if explicit:
            return 0.98
        if known:
            return 0.80
        return 0.35

    @staticmethod
    def _evidence_requirements(
        reaction_id: str,
        target_product: str | None,
        material_family: str,
        candidate_design: bool,
    ) -> list[str]:
        values = ["traceable_title_doi_abstract"]
        if reaction_id != "UNKNOWN":
            values.append("reaction_specific")
        if target_product:
            values.append("target_product_specific")
        if material_family == "high_entropy_alloy":
            values.append("high_entropy_alloy_specific")
        if candidate_design:
            values.append("explicit_five_element_composition")
        return values

    @staticmethod
    def _query_terms(
        reaction_family: str,
        target_product: str | None,
        material_family: str,
        candidate_design: bool,
    ) -> list[str]:
        values: list[str] = []
        values.extend(MATERIAL_QUERY_TERMS.get(material_family, []))
        values.extend(REACTION_QUERY_TERMS.get(reaction_family, []))
        values.extend(PRODUCT_QUERY_TERMS.get(str(target_product or ""), []))
        if candidate_design:
            values.append("explicit alloy composition")
        return list(dict.fromkeys(values))
