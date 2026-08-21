from __future__ import annotations

from typing import Any

from app.domain.reaction_profiles import (
    REACTION_PROFILES,
    detect_reaction_profile,
    get_reaction_profile,
)
from app.domain.llm_validation import strict_bool
from tools.llm_client import LLMError, OpenAICompatibleClient


class TaskAnalyzer:
    """从自然语言中提取科研任务，并绑定可信的反应档案。"""

    def __init__(
        self,
        llm: OpenAICompatibleClient | None = None,
    ) -> None:
        self.llm = llm or OpenAICompatibleClient()

    def analyze(self, question: str) -> dict[str, Any]:
        question = question.strip()

        if not question:
            raise ValueError("科研问题不能为空。")

        fallback_profile = detect_reaction_profile(question)

        if self.llm.available:
            try:
                return self._llm_analyze(
                    question=question,
                    fallback_profile=fallback_profile,
                )
            except (LLMError, ValueError, TypeError) as error:
                result = self._rule_analyze(
                    question,
                    fallback_profile,
                )
                result["analysis_warning"] = str(error)
                return result

        return self._rule_analyze(
            question,
            fallback_profile,
        )

    def _llm_analyze(
        self,
        question: str,
        fallback_profile: dict[str, Any],
    ) -> dict[str, Any]:
        valid_reaction_ids = list(
            REACTION_PROFILES.keys()
        )

        value = self.llm.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "你是电催化科研任务分析器。"
                        "你只负责识别任务，不生成候选材料，"
                        "不编造论文、性能、形成能或吸附能。"
                        "必须从允许的 reaction_id 中选择反应。"
                        "不确定时选择 UNKNOWN。"
                        "只输出合法 JSON，不输出 Markdown。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"用户问题：{question}\n"
                        f"允许的 reaction_id：{valid_reaction_ids}\n"
                        "请输出以下字段：\n"
                        "- reaction_id：字符串\n"
                        "- target_product：字符串或 null\n"
                        "- material_family：字符串\n"
                        "- research_goal：字符串\n"
                        "- user_constraints：字符串数组\n"
                        "- requested_outputs：字符串数组\n"
                        "- needs_candidate_design：布尔值\n"
                        "- needs_structure_modeling：布尔值\n"
                        "- needs_property_prediction：布尔值\n"
                        "- needs_dft：布尔值\n"
                    ),
                },
            ]
        )

        reaction_id = str(
            value.get("reaction_id", "UNKNOWN")
        ).strip()

        if reaction_id not in REACTION_PROFILES:
            raise ValueError(
                f"LLM 返回了不支持的 reaction_id: {reaction_id}"
            )

        # 对明确关键词优先使用本地反应档案，防止 LLM 错判。
        if fallback_profile["reaction_id"] != "UNKNOWN":
            reaction_id = fallback_profile["reaction_id"]

        profile = get_reaction_profile(reaction_id)

        return {
            "original_question": question,
            "reaction_id": reaction_id,
            "reaction_family": profile["reaction_family"],
            "target_product": (
                value.get("target_product")
                or profile.get("target_product")
            ),
            "material_family": str(
                value.get(
                    "material_family",
                    "unspecified",
                )
            ).strip(),
            "research_goal": str(
                value.get(
                    "research_goal",
                    question,
                )
            ).strip(),
            "user_constraints": self._string_list(
                value.get("user_constraints", [])
            ),
            "requested_outputs": self._string_list(
                value.get("requested_outputs", [])
            ),
            "needs_candidate_design": strict_bool(
                value.get("needs_candidate_design", False),
                field="needs_candidate_design",
            ),
            "needs_structure_modeling": strict_bool(
                value.get("needs_structure_modeling", False),
                field="needs_structure_modeling",
            ),
            "needs_property_prediction": strict_bool(
                value.get("needs_property_prediction", False),
                field="needs_property_prediction",
            ),
            "needs_dft": strict_bool(
                value.get("needs_dft", False), field="needs_dft"
            ),
            "reaction_profile": profile,
            "analysis_mode": "llm",
        }

    def _rule_analyze(
        self,
        question: str,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        lower = question.lower()

        material_family = "unspecified"

        if any(
            term in lower
            for term in (
                "高熵合金",
                "高熵催化剂",
                "high entropy alloy",
                "hea",
            )
        ):
            material_family = "high_entropy_alloy"

        needs_candidate_design = any(
            term in lower
            for term in (
                "设计",
                "候选",
                "推荐",
                "筛选",
                "design",
                "candidate",
                "recommend",
                "screen",
            )
        )

        needs_structure_modeling = any(
            term in lower
            for term in (
                "结构",
                "建模",
                "设计",
                "构造",
                "构建",
                "建立",
                "fcc",
                "cif",
                "poscar",
                "structure",
                "modeling",
            )
        )
        if profile.get("reaction_id") in {"OER", "ORR", "NRR"}:
            needs_structure_modeling = needs_structure_modeling or any(
                term in lower
                for term in (
                    "design",
                    "model",
                    "结构",
                    "建模",
                    "设计",
                    "构造",
                    "构建",
                    "建立",
                )
            )

        needs_property_prediction = any(
            term in lower
            for term in (
                "预测",
                "形成能",
                "性质",
                "cgcnn",
                "predict",
                "formation energy",
                "property",
            )
        )

        needs_dft = any(
            term in lower
            for term in (
                "dft",
                "vasp",
                "吸附能",
                "反应势垒",
                "自由能",
            )
        )

        return {
            "original_question": question,
            "reaction_id": profile["reaction_id"],
            "reaction_family": profile["reaction_family"],
            "target_product": profile.get("target_product"),
            "material_family": material_family,
            "research_goal": question,
            "user_constraints": [],
            "requested_outputs": [],
            "needs_candidate_design": needs_candidate_design,
            "needs_structure_modeling": needs_structure_modeling,
            "needs_property_prediction": needs_property_prediction,
            "needs_dft": needs_dft,
            "reaction_profile": profile,
            "analysis_mode": "rule_fallback",
        }

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []

        result: list[str] = []

        for item in value:
            text = str(item).strip()
            if text and text not in result:
                result.append(text)

        return result
