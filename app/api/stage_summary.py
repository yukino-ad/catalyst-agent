from __future__ import annotations

from typing import Any


def summarize_stage(node: str, output: Any) -> str:
    value = output if isinstance(output, dict) else {}
    if node == "task_analysis":
        analysis = value.get("task_analysis", {})
        if not isinstance(analysis, dict):
            return "已完成任务要素识别"
        reaction = analysis.get("reaction_name") or analysis.get("reaction_id")
        material = analysis.get("material_family") or analysis.get("material_type")
        parts = [str(item) for item in (reaction, material) if item]
        return f"已识别：{' + '.join(parts)}" if parts else "已完成反应、材料和目标识别"
    if node == "capability_gate":
        capability = value.get("capability", {})
        unsupported = capability.get("unsupported", []) if isinstance(capability, dict) else []
        return f"已完成能力检查，{len(unsupported)} 项能力需要注意边界" if unsupported else "能力检查通过，已确认可用工具范围"
    if node == "router":
        route = value.get("route", {})
        mode = route.get("route") or route.get("router_mode") or route.get("intent") if isinstance(route, dict) else ""
        return f"已选择 {mode} 工作流" if mode else "已选择适合本任务的工作流分支"
    if node == "planner":
        plan = value.get("plan", {})
        keywords = plan.get("keywords", []) if isinstance(plan, dict) else []
        return f"已生成任务计划，包含 {len(keywords)} 个检索或执行关键词" if keywords else "已生成结构化任务计划"
    if node == "literature_evidence":
        local_count = _count(value.get("local_literature_result", {}), "selected", "selected_count")
        online_count = _count(value.get("online_literature_result", {}), "candidates", "candidate_count")
        final_count = _count(value.get("merged_literature_result", {}), "selected", "selected_count")
        return f"本地召回 {local_count} 篇，联网补充 {online_count} 篇，{final_count} 篇进入证据审查"
    if node == "literature_assertion_extraction":
        extraction = value.get("literature_assertion_extraction", {})
        papers = extraction.get("papers", []) if isinstance(extraction, dict) else []
        assertion_count = sum(
            len(paper.get("assertions", []))
            for paper in papers
            if isinstance(paper, dict) and isinstance(paper.get("assertions", []), list)
        )
        return f"已完成科学断言提取，共 {assertion_count} 条"
    if node == "literature_review":
        review = value.get("literature_review", {})
        if not isinstance(review, dict):
            return "B6 文献人工审查已处理"
        if review.get("status") == "review_failed":
            return "B6 文献审查失败，未进入候选设计"
        return (
            f"B6 审查完成：接受 {int(review.get('accepted_count', 0) or 0)} 篇，"
            f"接受 {len(review.get('accepted_assertions', [])) if isinstance(review.get('accepted_assertions', []), list) else 0} 条科学断言"
        )
    if node == "structure_modeling":
        result = value.get("structure_modeling", value)
        count = _count(result, "structures", "structure_count")
        return f"已建立 {count} 个 FCC bulk 结构" if count else "FCC bulk 建模完成"
    if node == "formation_energy":
        result = value.get("formation_energy_evaluation", value)
        count = _count(result, "structures", "structure_count")
        predicted = int(result.get("cgcnn_predicted_count", 0) or 0) if isinstance(result, dict) else 0
        failed = int(result.get("failed_count", 0) or 0) if isinstance(result, dict) else 0
        return f"CGCNN 已预测 {predicted}/{count} 个结构的形成能，失败 {failed} 个"
    if node == "stability_screening":
        result = value.get("stability_screening", value)
        passed = int(result.get("passed_count", 0) or 0) if isinstance(result, dict) else 0
        failed = int(result.get("failed_count", 0) or 0) if isinstance(result, dict) else 0
        return f"稳定性判据完成：通过 {passed} 个，未通过 {failed} 个"
    if node == "slab_generation":
        result = value.get("slab_generation", value)
        count = _count(result, "slabs", "slab_count")
        return f"已构建 {count} 个 (111) slab" if count else "表面 slab 构建完成"
    if node == "slab_quality":
        result = value.get("slab_quality", value)
        passed = int(result.get("passed_count", 0) or 0) if isinstance(result, dict) else 0
        failed = int(result.get("failed_count", 0) or 0) if isinstance(result, dict) else 0
        return f"slab 质量检查完成：通过 {passed} 个，未通过 {failed} 个"
    status = str(value.get("status", "")).strip()
    return status.replace("_", " ") if status else "该阶段已完成"


def _count(value: Any, list_key: str, count_key: str) -> int:
    if isinstance(value, dict):
        count = value.get(count_key)
        if isinstance(count, int):
            return count
        items = value.get(list_key)
        if isinstance(items, list):
            return len(items)
    return 0
