from __future__ import annotations

import json
from typing import Any

from app.domain.llm_validation import unique_string_list
from tools.llm_client import LLMError, OpenAICompatibleClient


class TaskPlanner:
    """Create a structured research plan with an LLM and a deterministic fallback."""

    def __init__(self, llm: OpenAICompatibleClient | None = None) -> None:
        self.llm = llm or OpenAICompatibleClient()

    def plan(
        self,
        question: str,
        task_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_context = task_context or {}
        if self.llm.available:
            try:
                plan = self._llm_plan(question, task_context)
            except (LLMError, ValueError, TypeError) as error:
                plan = self._rule_plan(question, task_context)
                plan["planner_warning"] = str(error)
        else:
            plan = self._rule_plan(question, task_context)
        return self._apply_context(plan, task_context)

    def _llm_plan(
        self,
        question: str,
        task_context: dict[str, Any],
    ) -> dict[str, Any]:
        schema = {
            "question": "原始问题",
            "reaction": "目标反应",
            "product": "目标产物",
            "objective": "一句话科研目标",
            "constraints": ["材料或计算约束"],
            "keywords": ["英文检索词，6-12个"],
            "required_evidence": ["规划需要哪些文献证据"],
            "steps": ["按执行顺序列出后端工具步骤"],
        }
        value = self.llm.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "你是高熵合金与电催化科研任务规划器。"
                        "只输出合法 JSON，不输出 Markdown。不要编造文献、数值或计算结果。"
                        "规划应把文献检索、候选生成、结构建模、代理模型预测、稳定性筛选和 DFT 验证分开。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"科研问题：{question}\n"
                        "已校验任务上下文："
                        f"{json.dumps(task_context, ensure_ascii=False)}\n"
                        "检索词必须覆盖已确认的反应、目标产物、材料类型和证据要求。"
                        "未确认字段不得猜测。\n"
                        f"严格按此结构返回：{schema}"
                    ),
                },
            ]
        )
        required = {"reaction", "product", "objective", "keywords", "steps"}
        if not required.issubset(value):
            raise ValueError(f"规划结果缺少字段: {sorted(required - set(value))}")
        if not isinstance(value["keywords"], list) or not isinstance(value["steps"], list):
            raise TypeError("keywords 和 steps 必须是数组。")
        for field in ("constraints", "keywords", "required_evidence", "steps"):
            value[field] = unique_string_list(value.get(field, []), field=field)
        for field in ("reaction", "objective"):
            if not isinstance(value.get(field), str) or not value[field].strip():
                raise TypeError(f"{field} must be a non-empty string")
            value[field] = value[field].strip()
        product = value.get("product")
        if product is not None and not isinstance(product, str):
            raise TypeError("product must be a string or null")
        value["question"] = question
        value["planner_mode"] = "llm"
        return value

    def _rule_plan(
        self,
        question: str,
        task_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_context = task_context or {}
        product = (
            task_context.get("target_product")
            if task_context
            else self._detect_product(question)
        )
        reaction = task_context.get("reaction_family") or "CO2 reduction reaction"
        product_label = product or "未指定产物"
        return {
            "question": question,
            "reaction": reaction,
            "product": product,
            "objective": f"设计用于 {reaction} 生成 {product_label} 的高熵合金候选",
            "constraints": ["五元高熵体系", "FCC bulk", "先代理模型筛选，再进行 DFT 验证"],
            "keywords": (
                self._build_keywords(product)
                if product
                else [
                    "CO2 reduction",
                    "CO2RR",
                    "high entropy alloy",
                    "electrocatalyst",
                    "product selectivity",
                ]
            ),
            "required_evidence": ["候选元素依据", "关键吸附中间体", "选择性描述符", "相稳定性风险"],
            "steps": [
                f"检索 {reaction} 与高熵催化剂文献证据",
                "根据证据生成与排序五元候选",
                "生成 32 原子 FCC bulk 结构",
                "使用 CGCNN 预测形成能",
                "人工确认后执行 delta/Omega 稳定性判据",
                "为通过者生成 48 原子 (111) slab",
                "准备后续吸附能与 DFT 验证任务",
            ],
            "planner_mode": "rule_fallback",
        }

    @staticmethod
    def _apply_context(
        plan: dict[str, Any],
        task_context: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(plan)
        query_terms = [
            str(value).strip()
            for value in task_context.get("query_terms", [])
            if str(value).strip()
        ]
        keywords = [
            str(value).strip()
            for value in result.get("keywords", [])
            if str(value).strip()
        ]
        result["keywords"] = list(dict.fromkeys([
            *query_terms,
            *keywords,
        ]))
        requirements = [
            str(value).strip()
            for value in task_context.get("evidence_requirements", [])
            if str(value).strip()
        ]
        existing = [
            str(value).strip()
            for value in result.get("required_evidence", [])
            if str(value).strip()
        ]
        result["required_evidence"] = list(dict.fromkeys([
            *requirements,
            *existing,
        ]))
        if task_context:
            result["reaction"] = task_context.get("reaction_family")
            result["product"] = task_context.get("target_product")
            result["online_preference"] = task_context.get("online_preference")
            result["unresolved_fields"] = task_context.get("unresolved_fields", [])
            result["canonical_context_used"] = True
        return result

    @staticmethod
    def _detect_product(question: str) -> str:
        lower = question.lower()
        if "甲酸" in question or "formate" in lower:
            return "HCOO-"
        if "甲醇" in question or "methanol" in lower:
            return "CH3OH"
        if "乙烯" in question or "ethylene" in lower:
            return "C2H4"
        return "CO"

    @staticmethod
    def _build_keywords(product: str) -> list[str]:
        additions = {
            "CO": ["COOH intermediate", "CO adsorption"],
            "HCOO-": ["formate pathway", "Sn catalyst", "In catalyst"],
            "HCOOH/HCOO-": [
                "formate pathway",
                "formic acid selectivity",
                "Sn catalyst",
                "In catalyst",
            ],
            "CH3OH": ["methanol selectivity", "multi-electron reduction"],
            "C2H4": ["ethylene", "C-C coupling", "Cu catalyst"],
        }
        return [
            "CO2 reduction", "CO2RR", "high entropy alloy", "electrocatalyst"
        ] + additions.get(product, [])
