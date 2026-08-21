from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from langgraph.types import Command

from app.api.review_contract import validate_review_decision
from app.api.state_presenter import safe_interrupt, stage_details
from app.api.stage_summary import summarize_stage
from app.api.stage_outputs import safe_stage_outputs
from app.api.workflow_timeline import (
    create_timeline,
    finalize_timeline,
    mark_node_update,
    stage_id_for_review,
    update_stage,
)
from app.domain.workflow_run_repository import WorkflowRunRepository
from dotenv import load_dotenv
from pathlib import Path
from app.api.connection_status import web_remote_operations_enabled


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)

# The browser may only inherit cluster permissions behind one explicit master switch.
if not web_remote_operations_enabled():
    os.environ["CLUSTER_PREFLIGHT_ENABLED"] = "false"
    os.environ["CLUSTER_REMOTE_WRITE_ENABLED"] = "false"
    os.environ["CLUSTER_SUBMISSION_ENABLED"] = "false"


class TaskManager:
    def __init__(
        self,
        repository: WorkflowRunRepository | None = None,
        graph: Any | None = None,
        executor: Any | None = None,
    ) -> None:
        self.repository = repository or WorkflowRunRepository()
        self._graph = graph
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="catalyst-api"
        )
        self._lock = threading.Lock()
        from app.domain.cgcnn_training_manager import CGCNNTrainingManager
        self._cgcnn_training_manager = CGCNNTrainingManager()

    def create(self, question: str) -> dict[str, Any]:
        normalized = str(question or "").strip()
        if not normalized:
            raise ValueError("科研问题不能为空。")
        task_id = (
            f"web-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:6]}"
        )
        record = self.repository.update(task_id, {
            "question": normalized,
            "workflow_status": "queued",
            "stage": "created",
            "stage_label": "任务已创建，等待 Agent 运行",
            "progress": 2,
            "waiting_for_human": False,
            "review_type": "",
            "review": {},
            "message": "任务已进入后台队列。",
            "error": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "assistant-ui",
            "remote_operations_allowed": web_remote_operations_enabled(),
            "workflow_timeline": create_timeline(),
            "stage_events": [],
            "review_history": [],
            "consultation_history": [],
            "active_consultation": {},
            "consultation_pause_requested": False,
            "consultation_pending_continue": False,
        })
        self._executor.submit(self._run, task_id, normalized)
        return record

    def get(self, task_id: str) -> dict[str, Any] | None:
        record = self.repository.get(task_id)
        if record is None:
            return None
        return self._refresh_formation_source_review(
            self._normalize_legacy_review(record)
        )

    def list(self, include_archived: bool = False) -> list[dict[str, Any]]:
        return [
            self._normalize_legacy_review(record)
            for record in self.repository.list_records(include_archived=include_archived)
        ]

    def archive(self, task_id: str) -> dict[str, Any]:
        return self.repository.archive(task_id)

    def formation_energy_structures(self, task_id: str) -> list[dict[str, Any]]:
        if self.repository.get(task_id) is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        snapshot = self._get_graph().get_state(
            {"configurable": {"thread_id": task_id}}
        )
        values = dict(snapshot.values or {})
        structures = values.get("formation_energy_structures", [])
        if not isinstance(structures, list) or not structures:
            structures = values.get("bulk_structures", [])
        return [dict(item) for item in structures if isinstance(item, dict)]

    def resume_plan(self, task_id: str) -> dict[str, str]:
        record = self.repository.get(task_id)
        if record is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        if record.get("workflow_status") == "waiting_for_human":
            return {
                "status": "waiting_for_human",
                "target": "current_review",
                "message": "任务已恢复到当前人工审查卡。",
            }
        try:
            from app.workflow_resume_cli import resolve_resume_target

            target = resolve_resume_target(record)
        except ValueError:
            target = "unsupported"
        if target == "complete" or record.get("workflow_status") == "completed":
            return {
                "status": "completed",
                "target": "complete",
                "message": "任务已经完成，无需重复执行。",
            }
        if target == "wait":
            return {
                "status": str(record.get("workflow_status", "unknown")),
                "target": "task_record",
                "message": "已载入任务记录；当前没有可自动执行的恢复节点。",
            }
        return {
            "status": str(record.get("workflow_status", "waiting")),
            "target": target,
            "message": "已识别恢复位置；请在任务详情中继续对应人工门或监控步骤。",
        }

    def continue_after_consultation(
        self,
        task_id: str,
        consultation_id: str = "",
    ) -> dict[str, Any]:
        record = self.repository.get(task_id)
        if record is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        if not record.get("consultation_pending_continue"):
            raise RuntimeError("Task has no consultation waiting for continuation.")
        history = [
            dict(item)
            for item in record.get("consultation_history", [])
            if isinstance(item, dict)
        ]
        known_ids = {str(item.get("consultation_id", "")) for item in history}
        if consultation_id and consultation_id not in known_ids:
            raise RuntimeError("Consultation does not belong to this task.")
        for item in history:
            if item.get("requires_continue_confirmation") and not item.get("continued"):
                item["continued"] = True
                item["continued_at"] = datetime.now(timezone.utc).isoformat()
        previous = str(record.get("workflow_status_before_consultation", ""))
        paused = record.get("workflow_status") == "paused_for_consultation"
        changes = {
            "consultation_history": history,
            "active_consultation": {},
            "consultation_pause_requested": False,
            "consultation_pending_continue": False,
            "message": "咨询已结束，工作流正在继续。" if paused else "咨询已结束。",
        }
        if paused:
            changes.update({
                "workflow_status": "resuming",
                "waiting_for_human": False,
            })
        elif previous:
            changes["workflow_status"] = record.get("workflow_status", previous)
        updated = self.repository.update(task_id, changes)
        if paused:
            self._executor.submit(self._continue_checkpoint, task_id)
        return updated

    def submit_review(
        self,
        task_id: str,
        review_id: str,
        review_type: str,
        decision: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        record = self.repository.get(task_id)
        if record is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        if record.get("last_review_idempotency_key") == idempotency_key:
            return record
        if record.get("workflow_status") != "waiting_for_human":
            raise RuntimeError("Task is not waiting for human review.")
        review = record.get("review", {})
        if not isinstance(review, dict):
            raise RuntimeError("Task has no valid review payload.")
        if review_type == "formation_energy_source_review_required":
            record = self._refresh_formation_source_review(record)
            review = record.get("review", {})
        if review_type == "dft_execution_options_required" and not review.get("options"):
            review = safe_interrupt(review)
        if review.get("review_id") != review_id:
            raise RuntimeError("Review is stale or does not belong to this task.")
        if record.get("review_type") != review_type:
            raise RuntimeError("Review type does not match the current interrupt.")
        if review_type in {
            "remote_upload_review_required",
            "remote_submission_review_required",
        } and not web_remote_operations_enabled():
            raise RuntimeError(
                "网页真实超算操作未启用；请设置 WEB_REMOTE_OPERATIONS_ENABLED=true 并重启后端。"
            )
        normalized = validate_review_decision(review, review_type, decision)
        timeline = record.get("workflow_timeline") or create_timeline()
        review_stage = stage_id_for_review(review_type)
        if review_stage:
            timeline = update_stage(
                timeline,
                review_stage,
                "running",
                summary="Human review submitted; workflow is resuming.",
            )
        review_history = self._submit_review_history(
            self._append_review_history(record.get("review_history", []), review),
            review_id,
            normalized,
        )
        updated = self.repository.update(task_id, {
            "workflow_status": "resuming",
            "waiting_for_human": False,
            "message": "人工决定已接收，正在恢复工作流。",
            "last_review_idempotency_key": idempotency_key,
            "last_review_submission": {
                "review_id": review_id,
                "review_type": review_type,
                "decision": normalized,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            },
            "review_history": review_history,
            "workflow_timeline": timeline,
        })
        self._executor.submit(self._resume, task_id, normalized)
        return updated

    def _refresh_formation_source_review(self, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("review_type") != "formation_energy_source_review_required":
            return record
        latest = self._cgcnn_training_manager.latest(str(record.get("task_id", "")))
        review = dict(record.get("review", {}))
        ready = bool(latest and latest.get("status") == "completed")
        review["temporary_model_ready"] = ready
        review["temporary_model_run_id"] = str(latest.get("run_id", "")) if latest else ""
        try:
            snapshot = self._get_graph().get_state({
                "configurable": {"thread_id": str(record.get("task_id", ""))}
            })
            structures = (snapshot.values or {}).get("formation_energy_structures", [])
        except Exception:
            structures = []
        temporary = {
            str(item.get("structure_id", "")): item
            for item in (
                self._cgcnn_training_manager.predictions(
                    str(record.get("task_id", "")),
                    str(latest.get("run_id", "")),
                )
                if ready and latest
                else []
            )
        }
        comparison = []
        for item in structures if isinstance(structures, list) else []:
            if not isinstance(item, dict) or item.get("formation_energy") is None:
                continue
            structure_id = str(item.get("structure_id", ""))
            production_value = item.get("formation_energy")
            temporary_value = (temporary.get(structure_id) or {}).get(
                "formation_energy_ev_per_atom"
            )
            comparison.append({
                "structure_id": structure_id,
                "pretrained_formation_energy_ev_per_atom": production_value,
                "temporary_formation_energy_ev_per_atom": temporary_value,
                "prediction_difference_ev_per_atom": (
                    float(temporary_value) - float(production_value)
                    if temporary_value is not None
                    else None
                ),
                "formation_energy_unit": "eV/atom",
            })
        review["items"] = comparison or review.get("items", [])
        options = []
        for item in review.get("options", []):
            option = dict(item) if isinstance(item, dict) else {}
            if option.get("mode") == "temporary_trained":
                option["disabled"] = not ready
                option["explanation"] = (
                    "本任务临时模型已完成，可用于全部候选。"
                    if ready
                    else f"临时训练状态：{latest.get('status') if latest else 'not_started'}。"
                )
            options.append(option)
        review["options"] = options
        history = []
        for item in record.get("review_history", []):
            entry = dict(item) if isinstance(item, dict) else {}
            if (
                entry.get("status") == "waiting"
                and entry.get("review_id") == review.get("review_id")
            ):
                entry["review"] = review
            history.append(entry)
        return {**record, "review": review, "review_history": history}

    @staticmethod
    def _normalize_legacy_review(record: dict[str, Any]) -> dict[str, Any]:
        normalized = record
        review = record.get("review", {})
        if (
            record.get("review_type") == "dft_execution_options_required"
            and isinstance(review, dict)
            and not review.get("options")
        ):
            normalized = {**record, "review": safe_interrupt(review)}

        c_mode = TaskManager._review_mode(
            normalized.get("review_history", []),
            "c_stage_execution_review_required",
        )
        if normalized.get("workflow_status") == "completed" and c_mode == "fcc_only":
            reason = "用户选择仅进行 FCC bulk 建模，因此后续科学计算未执行。"
            timeline = []
            for item in normalized.get("workflow_timeline", []):
                stage = dict(item) if isinstance(item, dict) else item
                if (
                    isinstance(stage, dict)
                    and stage.get("status") == "skipped"
                    and str(stage.get("stage_id", "")).startswith(("C6", "C7", "C8", "C9", "C10", "C11", "C12"))
                ):
                    stage["skip_reason"] = reason
                    stage["summary"] = reason
                timeline.append(stage)
            normalized = {
                **normalized,
                "message": (
                    "已按用户选择完成 FCC bulk 建模；未执行形成能预测、"
                    "稳定性判据、slab、DFT 或吸附计算。"
                ),
                "workflow_timeline": timeline,
            }
        if TaskManager._is_completed_legacy_c12(normalized):
            normalized = TaskManager._normalize_completed_legacy_c12(normalized)
        return normalized

    @staticmethod
    def _is_completed_legacy_c12(record: dict[str, Any]) -> bool:
        return bool(
            record.get("terminal") is True
            and record.get("workflow_status") == "adsorption_energy_review_completed"
            and isinstance(record.get("adsorption_energy_calculation"), dict)
        )

    @staticmethod
    def _normalize_completed_legacy_c12(record: dict[str, Any]) -> dict[str, Any]:
        task_id = str(record.get("task_id", ""))
        updated_at = str(record.get("updated_at", ""))
        selected_adsorbate = str(record.get("selected_adsorbate", ""))
        source = record.get("adsorption_source_slabs", {})
        source_slabs = source if isinstance(source, list) else [source] if isinstance(source, dict) else []
        source_slab = source_slabs[0] if source_slabs else {}
        jobs = record.get("adsorption_dft_jobs", [])
        jobs = jobs if isinstance(jobs, list) else [jobs] if isinstance(jobs, dict) else []
        energy_result = record.get("adsorption_energy_calculation", {})
        calculations = energy_result.get("calculations", []) if isinstance(energy_result, dict) else []
        calculation = calculations[0] if calculations and isinstance(calculations[0], dict) else {}
        parsed = record.get("adsorption_parsed_results", {})
        parsed_result = parsed.get("parsed_vasp_result", {}) if isinstance(parsed, dict) else {}

        timeline = create_timeline()
        legacy_reason = "该历史任务从已弛豫 clean slab 恢复进入 C12；旧记录未保存前序 A-C 时间线。"
        for stage in timeline:
            if stage["group"] != "C12":
                stage["status"] = "skipped"
                stage["summary"] = legacy_reason
                stage["skip_reason"] = legacy_reason
                stage["updated_at"] = updated_at

        stage_values = {
            "C12.1": (
                f"已选择单一吸附中间体 {selected_adsorbate or '未记录'}",
                {
                    "selected_adsorbate": selected_adsorbate,
                    "selected_adsorbate_count": 1 if selected_adsorbate else 0,
                    "status": "adsorption_reaction_plan_ready",
                },
            ),
            "C12.2": (
                "已继承弛豫后 clean slab CONTCAR 和总能量",
                {
                    "slab_id": source_slab.get("slab_id"),
                    "clean_slab_slurm_job_id": source_slab.get("clean_slab_slurm_job_id"),
                    "clean_slab_energy_ev": source_slab.get("clean_slab_energy_ev"),
                    "energy_unit": "eV",
                    "status": "clean_slab_result_ready",
                },
            ),
            "C12.3": (
                f"已建立 1 个 {selected_adsorbate or ''} 单吸附结构",
                {
                    "structure_count": len(jobs),
                    "items": [
                        {
                            "structure_id": job.get("adsorption_structure_id", job.get("job_id")),
                            "adsorbate": job.get("adsorbate"),
                            "site_type": job.get("site_type"),
                            "atom_count": (job.get("scientific_identity") or {}).get("atom_count")
                            if isinstance(job.get("scientific_identity"), dict) else None,
                        }
                        for job in jobs
                    ],
                    "status": "adsorption_structure_generated",
                },
            ),
            "C12.4": (
                "吸附结构已通过人工流程并进入 DFT",
                {"approved_count": len(jobs), "status": "adsorption_structure_approved"},
            ),
            "C12.5": (
                f"已准备 {len(jobs)} 个吸附体系 VASP 输入包",
                {"bundle_count": len(jobs), "status": "dft_input_preparation_completed"},
            ),
            "C12.6": (
                "吸附 DFT 已完成并下载解析结果",
                {
                    "job_count": len(jobs),
                    "slurm_job_id": parsed.get("slurm_job_id") if isinstance(parsed, dict) else None,
                    "scheduler_state": parsed.get("scheduler_state") if isinstance(parsed, dict) else None,
                    "vasp_decision": parsed.get("vasp_decision") if isinstance(parsed, dict) else None,
                    "adsorbed_energy_ev": parsed_result.get("final_toten_ev")
                    if isinstance(parsed_result, dict) else None,
                    "energy_unit": "eV",
                    "status": "adsorption_result_parsed",
                },
            ),
            "C12.7": (
                "三能量吸附能计算已完成人工审查",
                {
                    "calculation_count": len(calculations),
                    "approved_count": int((record.get("adsorption_energy_review") or {}).get("approved_count", 0))
                    if isinstance(record.get("adsorption_energy_review"), dict) else 0,
                    "items": [
                        {
                            "structure_id": item.get("adsorption_structure_id"),
                            "adsorbate": item.get("adsorbate"),
                            "adsorption_energy_ev": item.get("adsorption_energy_ev"),
                            "energy_unit": item.get("energy_unit", "eV"),
                        }
                        for item in calculations if isinstance(item, dict)
                    ],
                    "status": "adsorption_energy_review_completed",
                },
            ),
        }
        for stage_id, (summary, outputs) in stage_values.items():
            timeline = update_stage(timeline, stage_id, "completed", summary=summary, outputs=outputs)
        for stage in timeline:
            if stage.get("group") == "C12" and stage.get("status") == "completed":
                stage["started_at"] = updated_at
                stage["completed_at"] = updated_at
                stage["updated_at"] = updated_at

        events = [
            {
                "event_id": f"legacy-{task_id}-{stage['stage_id']}",
                "node_id": f"legacy_{stage['stage_id']}",
                "created_at": updated_at,
                "stage": dict(stage),
            }
            for stage in timeline
            if stage.get("group") == "C12" and stage.get("status") == "completed"
        ]

        review_result = record.get("adsorption_energy_review", {})
        decision = review_result.get("decision", {}) if isinstance(review_result, dict) else {}
        review_id = f"legacy-c12-7-{task_id}"
        review_payload = safe_interrupt({
            "type": "adsorption_energy_review_required",
            "message": "历史 C12.7 三能量计算人工审查记录。",
            "calculations": calculations,
            "requires_human_confirmation": True,
            "next_stage": "completed",
        })
        review_payload["review_id"] = review_id
        review_history = [{
            "review_id": review_id,
            "review_type": "adsorption_energy_review_required",
            "status": "submitted",
            "review": review_payload,
            "decision": decision,
            "created_at": updated_at,
            "submitted_at": updated_at,
        }]
        energy = calculation.get("adsorption_energy_ev")
        return {
            **record,
            "question": str(record.get("question", "")).strip() or f"C12 {selected_adsorbate} 单吸附能历史任务",
            "workflow_status": "completed",
            "stage": "completed",
            "stage_label": "C12.7 吸附能审查已完成",
            "stage_summary": f"{selected_adsorbate} 吸附能 {energy:.6f} eV，已人工批准" if isinstance(energy, (int, float)) else "吸附能已完成人工审查",
            "progress": 100,
            "waiting_for_human": False,
            "review_type": "",
            "review": {},
            "message": "C12 单吸附计算、DFT 结果解析、三能量计算和人工审查均已完成。",
            "error": "",
            "workflow_timeline": timeline,
            "stage_events": events,
            "review_history": review_history,
        }

    @staticmethod
    def _review_mode(history_value: Any, review_type: str) -> str:
        if not isinstance(history_value, list):
            return ""
        for item in reversed(history_value):
            if not isinstance(item, dict) or item.get("review_type") != review_type:
                continue
            decision = item.get("decision", {})
            return str(decision.get("mode", "")) if isinstance(decision, dict) else ""
        return ""

    def _get_graph(self) -> Any:
        if self._graph is None:
            from app.graph.workflow import graph

            self._graph = graph
        return self._graph

    def _run(self, task_id: str, question: str) -> None:
        try:
            self.repository.update(task_id, {
                "workflow_status": "running",
                "stage": "task_analysis",
                "stage_label": stage_details("task_analysis")[0],
                "progress": stage_details("task_analysis")[1],
                "message": "Agent 已开始处理自然语言任务。",
            })
            initial_state = {
                "task_id": task_id,
                "question": question,
                "candidate_user_overrides": {
                    "required_elements": [],
                    "preferred_elements": [],
                    "excluded_elements": [],
                },
                "external_structure_request": {
                    "path": "",
                    "formation_energy": None,
                    "formation_energy_source": "",
                },
                "errors": [],
                "warnings": [],
                "retry_count": 0,
                "status": "created",
            }
            config = {"configurable": {"thread_id": task_id}}
            graph = self._get_graph()
            self._consume(task_id, graph, config, initial_state)
        except Exception as error:
            self._record_failure(task_id, error)

    def _resume(self, task_id: str, decision: dict[str, Any]) -> None:
        try:
            graph = self._get_graph()
            config = {"configurable": {"thread_id": task_id}}
            self._consume(task_id, graph, config, Command(resume=decision))
        except Exception as error:
            self._record_failure(task_id, error)

    def _continue_checkpoint(self, task_id: str) -> None:
        try:
            graph = self._get_graph()
            config = {"configurable": {"thread_id": task_id}}
            self._consume(task_id, graph, config, None)
        except Exception as error:
            self._record_failure(task_id, error)

    def _consume(
        self,
        task_id: str,
        graph: Any,
        config: dict[str, Any],
        graph_input: Any,
    ) -> None:
        last_interrupt: dict[str, Any] | None = None
        paused_for_consultation = False
        with self._lock:
            for chunk in graph.stream(graph_input, config=config, stream_mode="updates"):
                if not isinstance(chunk, dict):
                    continue
                if "__interrupt__" in chunk:
                    last_interrupt = self._extract_interrupt(chunk["__interrupt__"])
                    continue
                for node in chunk:
                    if node.startswith("__"):
                        continue
                    label, progress = stage_details(node)
                    summary = summarize_stage(node, chunk.get(node, {}))
                    current = self.repository.get(task_id) or {}
                    node_outputs = safe_stage_outputs(chunk.get(node, {}), node)
                    timeline = mark_node_update(
                        current.get("workflow_timeline") or create_timeline(),
                        node,
                        summary,
                        node_outputs,
                    )
                    stage_events = self._append_stage_events(
                        current.get("stage_events", []),
                        timeline,
                        node,
                    )
                    self.repository.update(task_id, {
                        "workflow_status": "running",
                        "stage": node,
                        "stage_label": label,
                        "progress": progress,
                        "waiting_for_human": False,
                        "review_type": "",
                        "review": {},
                        "message": label,
                        "stage_summary": summary or str(current.get("stage_summary", "")),
                        "workflow_timeline": timeline,
                        "stage_events": stage_events,
                    })
                    latest = self.repository.get(task_id) or {}
                    if latest.get("consultation_pause_requested"):
                        paused_for_consultation = True
                        break
                if paused_for_consultation:
                    break
            snapshot = graph.get_state(config)
            values = dict(snapshot.values or {})

        if paused_for_consultation:
            current = self.repository.get(task_id) or {}
            self.repository.update(task_id, {
                "workflow_status": "paused_for_consultation",
                "waiting_for_human": False,
                "stage_label": "工作流已在节点边界暂停",
                "message": "咨询回答完成后，请选择是否继续工作流。",
                "paused_stage": current.get("stage", ""),
                "resume_stage": getattr(snapshot, "next", None) or [],
            })
            return

        if last_interrupt:
            review_type = str(last_interrupt.get("type", "unknown"))
            current = self.repository.get(task_id) or {}
            timeline = current.get("workflow_timeline") or create_timeline()
            review_stage = stage_id_for_review(review_type)
            if review_stage:
                timeline = update_stage(
                    timeline,
                    review_stage,
                    "waiting_review",
                    summary=str(last_interrupt.get("message", "")),
                    requires_human_action=True,
                )
            review_history = self._append_review_history(
                current.get("review_history", []),
                last_interrupt,
            )
            self.repository.update(task_id, {
                "workflow_status": "waiting_for_human",
                "stage": review_type,
                "stage_label": self._review_label(review_type),
                "progress": self._current_progress(task_id),
                "waiting_for_human": True,
                "review_type": review_type,
                "review": last_interrupt,
                "message": last_interrupt.get("message", "等待人工操作。"),
                "agent_status": values.get("status", ""),
                "workflow_timeline": timeline,
                "review_history": review_history,
            })
            return

        stop_reason = str(values.get("workflow_stop_reason", "") or "")
        current = self.repository.get(task_id) or {}
        terminal_error = self._terminal_error(values)
        if terminal_error:
            failed_node, error_message = terminal_error
            timeline = finalize_timeline(
                current.get("workflow_timeline") or create_timeline(),
                failed_stage=failed_node,
                error=error_message,
                reason="工作流因阶段错误提前结束。",
            )
            self.repository.update(task_id, {
                "workflow_status": "failed",
                "stage": failed_node or "failed",
                "stage_label": stage_details("failed")[0],
                "progress": int(current.get("progress", 100)),
                "waiting_for_human": False,
                "review_type": "",
                "review": {},
                "message": "Agent 在科学工作流中遇到错误，后续阶段未执行。",
                "error": error_message,
                "agent_status": values.get("status", "failed"),
                "warning_count": len(values.get("warnings", [])),
                "error_count": len(values.get("errors", [])),
                "workflow_timeline": timeline,
            })
            return
        timeline = finalize_timeline(
            current.get("workflow_timeline") or create_timeline(),
            reason=stop_reason or "Workflow completed.",
        )
        agent_status = str(values.get("status", "completed") or "completed")
        terminal_message = self._terminal_message(stop_reason, agent_status)
        self.repository.update(task_id, {
            "workflow_status": "completed",
            "stage": "completed",
            "stage_label": stage_details("completed")[0],
            "progress": 100,
            "waiting_for_human": False,
            "review_type": "",
            "review": {},
            "message": terminal_message,
            "agent_status": agent_status,
            "workflow_stop_reason": stop_reason,
            "warning_count": len(values.get("warnings", [])),
            "error_count": len(values.get("errors", [])),
            "workflow_timeline": timeline,
        })

    @staticmethod
    def _append_stage_events(
        events: Any,
        timeline: list[dict[str, Any]],
        node_id: str,
    ) -> list[dict[str, Any]]:
        history = [dict(item) for item in events if isinstance(item, dict)] if isinstance(events, list) else []
        known = {str(item.get("event_id", "")) for item in history}
        for stage in timeline:
            if node_id not in stage.get("node_ids", []):
                continue
            updated_at = str(stage.get("updated_at", ""))
            event_id = f"{stage.get('stage_id', '')}:{node_id}:{updated_at}"
            if not updated_at or event_id in known:
                continue
            history.append({
                "event_id": event_id,
                "node_id": node_id,
                "created_at": updated_at,
                "stage": dict(stage),
            })
            known.add(event_id)
        return history[-200:]

    @staticmethod
    def _append_review_history(history_value: Any, review: dict[str, Any]) -> list[dict[str, Any]]:
        history = [dict(item) for item in history_value if isinstance(item, dict)] if isinstance(history_value, list) else []
        review_id = str(review.get("review_id", ""))
        if review_id and not any(item.get("review_id") == review_id for item in history):
            history.append({
                "review_id": review_id,
                "review_type": str(review.get("type", "")),
                "status": "waiting",
                "review": dict(review),
                "decision": {},
                "created_at": datetime.now(timezone.utc).isoformat(),
                "submitted_at": "",
            })
        return history[-100:]

    @staticmethod
    def _submit_review_history(
        history_value: Any,
        review_id: str,
        decision: dict[str, Any],
    ) -> list[dict[str, Any]]:
        history = [dict(item) for item in history_value if isinstance(item, dict)] if isinstance(history_value, list) else []
        submitted_at = datetime.now(timezone.utc).isoformat()
        for item in history:
            if item.get("review_id") != review_id:
                continue
            item["status"] = "submitted"
            item["decision"] = dict(decision)
            item["submitted_at"] = submitted_at
            break
        return history

    @staticmethod
    def _terminal_message(stop_reason: str, agent_status: str) -> str:
        if stop_reason:
            return f"工作流已结束：{stop_reason}"
        if agent_status.endswith("_skipped"):
            return "本次工作流分支已结束；后续步骤被跳过，未执行真实 DFT 提交。"
        return "工作流已完成。"

    @staticmethod
    def _terminal_error(values: dict[str, Any]) -> tuple[str, str] | None:
        status = str(values.get("status", "") or "")
        failed_node = ""
        if status.endswith("_failed"):
            failed_node = status.removesuffix("_failed")
        for node in ("literature_review", "candidate_review"):
            result = values.get(node, {})
            node_status = str(result.get("status", "")) if isinstance(result, dict) else ""
            if node_status.endswith("_failed") or node_status == "review_failed":
                failed_node = node
                break
        if not failed_node:
            return None
        errors = values.get("errors", [])
        last = errors[-1] if isinstance(errors, list) and errors else {}
        if not isinstance(last, dict):
            last = {}
        node = str(last.get("node", "") or failed_node)
        message = str(last.get("message", "") or status)
        return node, message

    def _record_failure(self, task_id: str, error: Exception) -> None:
        current = self.repository.get(task_id) or {}
        timeline = finalize_timeline(
            current.get("workflow_timeline") or create_timeline(),
            failed_stage=str(current.get("stage", "failed")),
            error=f"{type(error).__name__}: {error}",
            reason="Workflow failed before all stages completed.",
        )
        self.repository.update(task_id, {
                "workflow_status": "failed",
                "stage": "failed",
                "stage_label": stage_details("failed")[0],
                "progress": 100,
                "waiting_for_human": False,
                "review_type": "",
                "review": {},
                "message": "Agent 运行失败，请查看错误摘要。",
                "error": f"{type(error).__name__}: {error}",
                "workflow_timeline": timeline,
        })

    @staticmethod
    def _extract_interrupt(interrupts: Any) -> dict[str, Any] | None:
        if not interrupts:
            return None
        first = interrupts[0] if isinstance(interrupts, (list, tuple)) else interrupts
        value = getattr(first, "value", first)
        return safe_interrupt(value)

    def _current_progress(self, task_id: str) -> int:
        record = self.repository.get(task_id) or {}
        return int(record.get("progress", 50))

    @staticmethod
    def _review_label(review_type: str) -> str:
        labels = {
            "literature_review_required": "B6 等待文献人工审查",
            "candidate_review_required": "C4 等待候选人工选择",
            "c_stage_execution_review_required": "等待选择 C 阶段执行范围",
            "c7_dft_upgrade_review_required": "等待选择进入 DFT 的结构",
            "slab_review_required": "等待 slab 人工审查",
            "bulk_dft_input_review_required": "等待 bulk VASP 输入审查",
            "dft_input_review_required": "等待 slab VASP 输入审查",
            "dft_execution_options_required": "等待选择 DFT 执行参数",
            "remote_upload_review_required": "等待远程上传确认",
            "remote_submission_review_required": "等待 Slurm 提交确认",
        }
        return labels.get(review_type, "工作流等待人工操作")
