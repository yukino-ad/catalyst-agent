from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


# Keep the display model separate from LangGraph node names. Some scientific
# stages are currently implemented by one backend node, but remain visible.
STAGE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"stage_id": "A1", "node_ids": ("task_analysis",), "label": "理解任务", "group": "A", "progress": 6, "next": "A2"},
    {"stage_id": "A2", "node_ids": ("capability_gate",), "label": "检查能力", "group": "A", "progress": 10, "next": "A3"},
    {"stage_id": "A3", "node_ids": ("router",), "label": "选择工作流分支", "group": "A", "progress": 13, "next": "A4"},
    {"stage_id": "A4", "node_ids": ("planner",), "label": "生成任务计划", "group": "A", "progress": 16, "next": "B1"},
    {"stage_id": "B1", "node_ids": ("literature_evidence",), "label": "召回文献", "group": "B", "progress": 28, "next": "B2"},
    {"stage_id": "B2", "node_ids": ("literature_evidence",), "label": "检查文献元数据", "group": "B", "progress": 30, "next": "B3"},
    {"stage_id": "B3", "node_ids": ("literature_assertion_extraction",), "label": "分析任务相关性", "group": "B", "progress": 36, "next": "B4"},
    {"stage_id": "B4", "node_ids": ("literature_evidence",), "label": "联网检索学术文献", "group": "B", "progress": 32, "next": "B5"},
    {"stage_id": "B5", "node_ids": ("literature_assertion_extraction",), "label": "提取证据和科学断言", "group": "B", "progress": 40, "next": "B6"},
    {"stage_id": "B6", "node_ids": ("literature_review",), "label": "人工审查文献", "group": "B", "progress": 43, "next": "C1", "review_types": ("literature_review_required",)},
    {"stage_id": "C1", "node_ids": ("c_stage_preparation",), "label": "准备候选约束", "group": "C", "progress": 56, "next": "C2"},
    {"stage_id": "C2", "node_ids": ("candidate_generation",), "label": "生成候选组合", "group": "C", "progress": 61, "next": "C3"},
    {"stage_id": "C3", "node_ids": ("candidate_generation",), "label": "排序候选组合", "group": "C", "progress": 63, "next": "C4"},
    {"stage_id": "C4", "node_ids": ("candidate_review",), "label": "人工选择候选", "group": "C", "progress": 65, "next": "C5", "review_types": ("candidate_review_required", "c_stage_execution_review_required")},
    {"stage_id": "C5", "node_ids": ("structure_modeling",), "label": "建立 FCC bulk", "group": "C", "progress": 72, "next": "C6"},
    {"stage_id": "C6", "node_ids": ("formation_energy", "formation_energy_source_review"), "label": "预测并选择形成能", "group": "C", "progress": 78, "next": "C7", "review_types": ("formation_energy_source_review_required",)},
    {"stage_id": "C7", "node_ids": ("stability_screening",), "label": "执行稳定性判据", "group": "C", "progress": 80, "next": "C8", "review_types": ("c7_dft_upgrade_review_required",)},
    {"stage_id": "C8", "node_ids": ("slab_generation",), "label": "构建表面 slab", "group": "C", "progress": 85, "next": "C9"},
    {"stage_id": "C9", "node_ids": ("slab_quality",), "label": "检查 slab 质量", "group": "C", "progress": 87, "next": "C10", "review_types": ("slab_review_required",)},
    {"stage_id": "C10", "node_ids": ("bulk_dft_input_preview", "bulk_dft_input_review", "bulk_dft_input_finalize", "dft_input_preview", "dft_input_review", "dft_input_finalize"), "label": "准备 DFT 输入", "group": "C", "progress": 92, "next": "C11", "review_types": ("bulk_dft_input_review_required", "dft_input_review_required")},
    {"stage_id": "C11", "node_ids": ("dft_execution_options", "dft_local_preflight", "cluster_readonly_preflight", "remote_execution_plan", "remote_upload_review", "remote_upload", "remote_submission_review", "remote_submission", "submission_record"), "label": "提交和监控 DFT", "group": "C", "progress": 98, "next": "C12.1", "review_types": ("dft_execution_options_required", "remote_upload_review_required", "remote_submission_review_required")},
    {"stage_id": "C12.1", "node_ids": ("adsorption_reaction_planning",), "label": "选择吸附中间体", "group": "C12", "progress": 60, "next": "C12.2"},
    {"stage_id": "C12.2", "node_ids": ("clean_slab_result_adapter", "adsorption_source_filter", "adsorption_result_ready"), "label": "接收弛豫后 clean slab", "group": "C12", "progress": 64, "next": "C12.3"},
    {"stage_id": "C12.3", "node_ids": ("adsorption_site_generation", "adsorption_structure_generation", "adsorbate_structure_generation"), "label": "建立吸附位点结构", "group": "C12", "progress": 68, "next": "C12.4"},
    {"stage_id": "C12.4", "node_ids": ("adsorption_structure_quality", "adsorption_structure_review"), "label": "检查吸附结构", "group": "C12", "progress": 72, "next": "C12.5", "review_types": ("adsorption_structure_review_required",)},
    {"stage_id": "C12.5", "node_ids": ("adsorption_dft_preview", "adsorption_dft_review", "adsorption_dft_finalize", "adsorption_energy_input"), "label": "准备吸附 DFT 输入", "group": "C12", "progress": 76, "next": "C12.6", "review_types": ("adsorption_dft_input_review_required",)},
    {"stage_id": "C12.6", "node_ids": ("adsorption_dft_execution_options", "source_filter", "monitor", "completion", "result_ready"), "label": "监控吸附 DFT", "group": "C12", "progress": 88, "next": "C12.7", "review_types": ("adsorption_dft_execution_required",)},
    {"stage_id": "C12.7", "node_ids": ("adsorption_energy_calculation", "adsorption_energy_review"), "label": "审查吸附能", "group": "C12", "progress": 96, "next": "completed", "review_types": ("adsorption_energy_review_required",)},
)

VALID_STATUSES = {"pending", "running", "completed", "waiting_review", "skipped", "blocked", "failed"}


def create_timeline() -> list[dict[str, Any]]:
    return [
        {
            **deepcopy(stage),
            "node_ids": list(stage["node_ids"]),
            "review_types": list(stage.get("review_types", ())),
            "stage_label": stage["label"],
            "next_stage": stage["next"],
            "status": "pending",
            "summary": "",
            "outputs": {},
            "requires_human_action": False,
            "started_at": "",
            "completed_at": "",
            "updated_at": "",
            "skip_reason": "",
            "error": "",
        }
        for stage in STAGE_DEFINITIONS
    ]


def stage_ids_for_node(node_id: str) -> list[str]:
    return [str(stage["stage_id"]) for stage in STAGE_DEFINITIONS if node_id in stage["node_ids"]]


def stage_id_for_review(review_type: str) -> str | None:
    for stage in STAGE_DEFINITIONS:
        if review_type in stage.get("review_types", ()):
            return str(stage["stage_id"])
    return None


def update_stage(
    timeline: list[dict[str, Any]],
    stage_id: str,
    status: str,
    *,
    summary: str = "",
    requires_human_action: bool = False,
    skip_reason: str = "",
    error: str = "",
    outputs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown workflow timeline status: {status}")
    now = datetime.now(timezone.utc).isoformat()
    updated = deepcopy(timeline)
    for stage in updated:
        if stage.get("stage_id") != stage_id:
            continue
        if stage.get("status") == "completed" and status == "running":
            return updated
        stage["status"] = status
        stage["updated_at"] = now
        stage["requires_human_action"] = requires_human_action
        if status == "running" and not stage.get("started_at"):
            stage["started_at"] = now
        if status in {"completed", "skipped", "failed"}:
            stage["started_at"] = stage.get("started_at") or now
            stage["completed_at"] = now
        if summary:
            stage["summary"] = summary
        if skip_reason:
            stage["skip_reason"] = skip_reason
        if error:
            stage["error"] = error
        if outputs is not None:
            stage["outputs"] = deepcopy(outputs)
        break
    return updated


def mark_node_update(
    timeline: list[dict[str, Any]],
    node_id: str,
    summary: str = "",
    outputs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    stage_ids = stage_ids_for_node(node_id)
    timeline = _complete_resumed_review_stages(timeline, stage_ids)
    output_status = str((outputs or {}).get("status", ""))
    display_status = "skipped" if output_status.endswith("_skipped") else "completed"
    if node_id == "candidate_generation" and len(stage_ids) == 2:
        timeline = update_stage(timeline, "C2", "completed", summary=summary or "Candidates generated", outputs=outputs)
        return update_stage(timeline, "C3", "completed", summary=summary or "Candidates ranked", outputs=outputs)
    for stage_id in stage_ids:
        timeline = update_stage(
            timeline,
            stage_id,
            display_status,
            summary=summary,
            skip_reason=summary if display_status == "skipped" else "",
            outputs=outputs,
        )
    return timeline


def _complete_resumed_review_stages(
    timeline: list[dict[str, Any]],
    next_stage_ids: list[str],
) -> list[dict[str, Any]]:
    """Close submitted review stages once a later scientific node runs."""
    if not next_stage_ids:
        return timeline
    order = {str(stage["stage_id"]): index for index, stage in enumerate(STAGE_DEFINITIONS)}
    next_index = min(order[stage_id] for stage_id in next_stage_ids)
    updated = timeline
    for stage in list(updated):
        stage_id = str(stage.get("stage_id", ""))
        if stage.get("status") == "running" and order.get(stage_id, next_index) < next_index:
            updated = update_stage(
                updated,
                stage_id,
                "completed",
                summary="人工审查已提交，工作流已继续执行。",
            )
    return updated


def finalize_timeline(
    timeline: list[dict[str, Any]],
    *,
    reason: str = "Workflow ended before this stage was reached.",
    failed_stage: str = "",
    error: str = "",
) -> list[dict[str, Any]]:
    updated = timeline
    for stage in list(updated):
        stage_id = str(stage["stage_id"])
        if failed_stage and (failed_stage == stage_id or failed_stage in stage.get("node_ids", ())):
            updated = update_stage(updated, stage_id, "failed", error=error)
        elif stage.get("status") == "pending":
            updated = update_stage(updated, stage_id, "skipped", skip_reason=reason)
        elif stage.get("status") == "running":
            updated = update_stage(
                updated,
                stage_id,
                "completed",
                summary="人工审查已提交，本次分支随后结束。",
            )
    return updated
