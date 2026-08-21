from __future__ import annotations

from typing import Any


class CapabilityGate:
    """确定性检查当前 Agent 是否具备完成任务所需的工具。"""

    SUPPORT_ORDER = {
        "unsupported": 0,
        "literature_only": 1,
        "partial": 2,
        "full": 3,
    }

    def evaluate(
        self,
        task_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        profile = task_analysis.get(
            "reaction_profile",
            {},
        )
        tool_support = profile.get(
            "tool_support",
            {},
        )
        tool_support = dict(tool_support)

        # Candidate generation belongs to the C-stage capability contract.
        # Keep Reaction Profile focused on scientific metadata and avoid
        # contradictory declarations for the same runtime tool.
        c_stage = profile.get("c_stage_capability", {})
        if isinstance(c_stage, dict) and "candidate_generation" in c_stage:
            tool_support["candidate_generation"] = bool(
                c_stage["candidate_generation"]
            )

        requested_tools = self._requested_tools(
            task_analysis
        )

        available_tools: list[str] = []
        missing_tools: list[str] = []

        for tool in requested_tools:
            if tool_support.get(tool, False):
                available_tools.append(tool)
            else:
                missing_tools.append(tool)

        profile_level = profile.get(
            "support_level",
            "unsupported",
        )

        effective_level = self._effective_level(
            profile_level=profile_level,
            missing_tools=missing_tools,
            requested_tools=requested_tools,
        )

        can_continue_literature = bool(
            tool_support.get(
                "literature_rag",
                False,
            )
        )

        can_execute_all = (
            len(missing_tools) == 0
            and effective_level != "unsupported"
        )

        warnings: list[str] = []

        if missing_tools:
            warnings.append(
                "当前 Agent 尚不支持以下工具能力："
                + "、".join(missing_tools)
            )

        if (
            task_analysis.get(
                "needs_property_prediction"
            )
            and tool_support.get(
                "formation_energy_prediction"
            )
        ):
            warnings.append(
                "形成能预测只评价 bulk 稳定性，"
                "不能直接代表电催化活性或产物选择性。"
            )

        if not tool_support.get(
            "reaction_activity_prediction",
            False,
        ):
            warnings.append(
                "当前没有目标反应活性预测模型；"
                "反应活性仍需吸附能、DFT 或实验验证。"
            )

        return {
            "task_supported": (
                effective_level != "unsupported"
            ),
            "support_level": effective_level,
            "profile_support_level": profile_level,
            "can_continue_literature": (
                can_continue_literature
            ),
            "can_execute_all_requested_actions": (
                can_execute_all
            ),
            "requested_tools": requested_tools,
            "available_tools": available_tools,
            "missing_tools": missing_tools,
            "warnings": warnings,
            "reaction_id": profile.get(
                "reaction_id",
                "UNKNOWN",
            ),
            "decision_reason": self._decision_reason(
                effective_level,
                missing_tools,
            ),
        }

    @staticmethod
    def _requested_tools(
        task_analysis: dict[str, Any],
    ) -> list[str]:
        tools = ["literature_rag"]

        if task_analysis.get(
            "needs_candidate_design"
        ):
            tools.append(
                "candidate_generation"
            )

        if task_analysis.get(
            "needs_structure_modeling"
        ):
            tools.append(
                "fcc_bulk_modeling"
            )

        if task_analysis.get(
            "needs_property_prediction"
        ):
            tools.append(
                "formation_energy_prediction"
            )

        if task_analysis.get("needs_dft"):
            tools.append(
                "reaction_activity_prediction"
            )

        return list(dict.fromkeys(tools))

    @staticmethod
    def _effective_level(
        profile_level: str,
        missing_tools: list[str],
        requested_tools: list[str],
    ) -> str:
        if profile_level == "unsupported":
            return "unsupported"

        if not missing_tools:
            return profile_level

        if (
            requested_tools == ["literature_rag"]
            and "literature_rag" not in missing_tools
        ):
            return "literature_only"

        if "literature_rag" not in missing_tools:
            return "partial"

        return "unsupported"

    @staticmethod
    def _decision_reason(
        support_level: str,
        missing_tools: list[str],
    ) -> str:
        if support_level == "full":
            return "当前 Agent 可以执行本阶段请求的全部工具流程。"

        if support_level == "partial":
            return (
                "当前 Agent 可以完成文献分析和部分后端任务，"
                "但仍有工具能力缺失。"
            )

        if support_level == "literature_only":
            return (
                "当前仅支持文献检索与证据总结，"
                "不应启动后续建模或性质预测。"
            )

        if missing_tools:
            return (
                "当前任务超出 Agent 能力范围，缺少："
                + "、".join(missing_tools)
            )

        return "当前任务尚未得到支持。"
