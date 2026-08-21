from __future__ import annotations

import json
from typing import Any

from tools.llm_client import LLMError, OpenAICompatibleClient


class TaskRouter:
    """Let the LLM choose knowledge tools while deterministic code keeps execution bounds."""

    def __init__(self, llm: OpenAICompatibleClient | None = None) -> None:
        self.llm = llm or OpenAICompatibleClient()

    def route(
        self,
        question: str,
        task_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_context = task_context or {}
        if self.llm.available:
            try:
                route = self._llm_route(question, task_context)
            except (LLMError, ValueError, TypeError) as error:
                route = self._rule_route(question, task_context)
                route["router_warning"] = str(error)
        else:
            route = self._rule_route(question, task_context)
        return self._apply_context(route, question, task_context)

    def _llm_route(
        self,
        question: str,
        task_context: dict[str, Any],
    ) -> dict[str, Any]:
        value = self.llm.chat_json([
            {
                "role": "system",
                "content": (
                    "你是材料科研 Agent 的入口决策器。先理解用户真实意图，再决定是否需要文献 RAG。"
                    "当任务涉及材料设计、候选推荐、反应机理、文献事实、性质依据、元素选择或科研结论时，"
                    "通常应启用 RAG；纯文件操作、格式转换、打开可视化软件或用户明确要求不检索时可跳过。"
                    "你拥有工具编排决策权，但不能取消原子数、元素支持、路径、数据完整性等确定性约束。"
                    "只输出合法 JSON，不输出 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户指令：{question}\n"
                    "已校验任务上下文："
                    f"{json.dumps(task_context, ensure_ascii=False)}\n"
                    "必须以已校验上下文中的反应、产物、材料类型、"
                    "联网偏好和证据要求为准，不得自行改写。\n"
                    "输出字段：intent（简短意图）、use_rag（布尔值）、rag_reason（理由）、"
                    "rag_query（检索问题，跳过时为空字符串）、rag_focus（字符串数组）、"
                    "requested_actions（字符串数组）。"
                ),
            },
        ])
        if type(value.get("use_rag")) is not bool:
            raise TypeError("入口路由的 use_rag 必须是布尔值。")
        for field in ("rag_focus", "requested_actions"):
            if not isinstance(value.get(field, []), list):
                raise TypeError(f"入口路由的 {field} 必须是数组。")
        return {
            "intent": str(value.get("intent", question)).strip(),
            "use_rag": value["use_rag"],
            "rag_reason": str(value.get("rag_reason", "")).strip(),
            "rag_query": str(value.get("rag_query", "")).strip() if value["use_rag"] else "",
            "rag_focus": [str(item).strip() for item in value.get("rag_focus", []) if str(item).strip()],
            "requested_actions": [
                str(item).strip() for item in value.get("requested_actions", []) if str(item).strip()
            ],
            "router_mode": "llm",
        }

    @staticmethod
    def _rule_route(
        question: str,
        task_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_context = task_context or {}
        lower = question.lower()
        explicit_skip = any(term in lower for term in ("不检索", "不用检索", "skip rag", "no rag"))
        knowledge_terms = (
            "设计", "推荐", "筛选", "候选", "催化", "反应", "机理", "文献", "依据",
            "元素", "吸附", "性质", "稳定", "formation", "catalyst", "reaction",
            "mechanism", "literature", "candidate", "screen",
        )
        use_rag = not explicit_skip and any(term in lower for term in knowledge_terms)
        return {
            "intent": question.strip(),
            "use_rag": use_rag,
            "rag_reason": "任务需要外部科研证据。" if use_rag else "任务可由本地确定性工具完成。",
            "rag_query": (
                str(task_context.get("search_query", "")).strip()
                or question.strip()
            ) if use_rag else "",
            "rag_focus": list(task_context.get("evidence_requirements", [])),
            "requested_actions": [],
            "router_mode": "rule_fallback",
        }

    @staticmethod
    def _apply_context(
        route: dict[str, Any],
        question: str,
        task_context: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(route)
        preference = str(task_context.get("online_preference", "auto"))
        evidence_requirements = [
            str(value).strip()
            for value in task_context.get("evidence_requirements", [])
            if str(value).strip()
        ]
        needs_evidence = bool(
            task_context.get("needs_candidate_design")
            or evidence_requirements
        )
        explicit_skip = any(term in question.lower() for term in (
            "不检索", "不用检索", "skip rag", "no rag",
        ))
        requires_clarification = bool(
            task_context.get("requires_clarification", False)
        )
        if requires_clarification:
            result["use_rag"] = False
            result["rag_reason"] = (
                "关键反应信息尚不明确，先等待用户澄清。"
            )
        elif explicit_skip:
            result["use_rag"] = False
        elif needs_evidence:
            result["use_rag"] = True

        if result.get("use_rag"):
            result["rag_query"] = (
                str(task_context.get("search_query", "")).strip()
                or str(result.get("rag_query", "")).strip()
                or question.strip()
            )
            result["rag_focus"] = list(dict.fromkeys([
                *evidence_requirements,
                *[
                    str(value).strip()
                    for value in result.get("rag_focus", [])
                    if str(value).strip()
                ],
            ]))
        else:
            result["rag_query"] = ""
        result["online_preference"] = preference
        result["requires_clarification"] = requires_clarification
        result["clarification_question"] = task_context.get(
            "clarification_question",
            "",
        )
        result["canonical_context_used"] = bool(task_context)
        return result
