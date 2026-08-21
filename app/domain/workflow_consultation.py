from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator

from app.domain.workflow_run_repository import WorkflowRunRepository
from tools.llm_client import LLMError, OpenAICompatibleClient


INTENTS = {
    "workflow_command",
    "vasp_consultation",
    "scientific_explanation",
    "report_request",
    "general_research_chat",
}

SCIENTIFIC_RULES = """
Project rules that cannot be changed by the model:
- Formation energy and adsorption energy are different targets and datasets.
- E_ads = E_slab+adsorbate - E_clean_slab - E_reference. All three energies
  require consistent functional and calculation parameters.
- A negative adsorption energy alone does not prove catalytic activity.
- FCC is a modeling starting point, not experimental phase proof.
- C7 uses the project's configured formation-energy and delta/Omega criteria.
  Explain those criteria but never silently change their thresholds.
- CGCNN predictions are prescreening results, not DFT results.
- Never invent a structure, energy, convergence result, DOI, or completed job.
""".strip()


class WorkflowConsultationService:
    """Answer task-aware questions without mutating scientific workflow state."""

    def __init__(
        self,
        repository: WorkflowRunRepository | None = None,
        llm: OpenAICompatibleClient | None = None,
    ) -> None:
        self.repository = repository or WorkflowRunRepository()
        self.llm = llm or OpenAICompatibleClient()

    def respond(self, question: str, task_id: str = "") -> dict[str, Any]:
        text = str(question or "").strip()
        if not text:
            raise ValueError("咨询问题不能为空。")
        record = self.repository.get(task_id) if task_id else None
        if task_id and record is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        intent = self.classify(text, record)
        if intent == "workflow_command" and not record:
            return {
                "intent": intent,
                "create_workflow": True,
                "answer": "已识别为工作流指令。",
                "requires_continue_confirmation": False,
            }
        if intent == "report_request" and not record:
            return {
                "intent": intent,
                "create_workflow": False,
                "answer": "请先选择一个已有 task_id，报告必须依据真实任务记录生成。",
                "requires_continue_confirmation": False,
            }

        consultation_started_at = self._now()
        record = self._request_pause(task_id, record)
        consultation_id = f"consult-{uuid.uuid4().hex[:12]}"
        context = self._safe_context(record)
        answer, source = self._answer(intent, text, context)
        workflow_status = str((record or {}).get("workflow_status", ""))
        requires_continue_confirmation = bool(record)
        value = {
            "schema_version": "consultation-v1",
            "consultation_id": consultation_id,
            "task_id": task_id,
            "intent": intent,
            "question": text,
            "answer": answer,
            "answer_source": source,
            "paused_stage": str((record or {}).get("stage", "")),
            "requires_continue_confirmation": requires_continue_confirmation,
            "continued": False,
            "created_at": consultation_started_at,
        }
        if record:
            history = [
                dict(item)
                for item in record.get("consultation_history", [])
                if isinstance(item, dict)
            ]
            history.append(value)
            self.repository.update(task_id, {
                "consultation_history": history[-100:],
                "active_consultation": value,
                "consultation_pause_requested": workflow_status in {
                    "queued", "running", "resuming"
                },
                "consultation_pending_continue": requires_continue_confirmation,
                "workflow_status_before_consultation": workflow_status,
            })
        return {**value, "create_workflow": False}

    def respond_stream(self, question: str, task_id: str = "") -> Iterator[dict[str, Any]]:
        """Stream a Kimi answer, then persist the complete consultation record."""

        text, record = self._request_context(question, task_id)
        intent = self.classify(text, record)
        immediate = self._immediate_response(intent, record)
        if immediate is not None:
            yield {"type": "final", "result": immediate}
            return

        consultation_started_at = self._now()
        record = self._request_pause(task_id, record)
        context = self._safe_context(record)
        answer_parts: list[str] = []
        source = "kimi"
        if intent == "report_request" or not self.llm.available:
            source = "local_rules"
            answer = self._fallback_answer(intent, text, context)
            answer_parts.append(answer)
            yield {"type": "delta", "delta": answer}
        else:
            try:
                for delta in self.llm.chat_stream(
                    self._answer_messages(intent, text, context),
                    max_tokens=8192,
                    timeout_seconds=180,
                ):
                    answer_parts.append(delta)
                    yield {"type": "delta", "delta": delta}
            except LLMError as error:
                source = "local_fallback"
                fallback = self._fallback_answer(intent, text, context)
                if answer_parts:
                    fallback = f"\n\n{fallback}"
                fallback += f"\n\nKimi 暂不可用：{self._safe_error(error)}"
                answer_parts.append(fallback)
                yield {"type": "delta", "delta": fallback}

        result = self._persist_consultation(
            intent=intent,
            question=text,
            answer="".join(answer_parts).strip(),
            source=source,
            task_id=task_id,
            record=record,
            created_at=consultation_started_at,
        )
        yield {"type": "final", "result": result}

    def _request_context(
        self, question: str, task_id: str
    ) -> tuple[str, dict[str, Any] | None]:
        text = str(question or "").strip()
        if not text:
            raise ValueError("Consultation question cannot be empty.")
        record = self.repository.get(task_id) if task_id else None
        if task_id and record is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        return text, record

    @staticmethod
    def _immediate_response(
        intent: str, record: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if intent == "workflow_command" and not record:
            return {
                "intent": intent,
                "create_workflow": True,
                "answer": "已识别为工作流指令。",
                "requires_continue_confirmation": False,
            }
        if intent == "report_request" and not record:
            return {
                "intent": intent,
                "create_workflow": False,
                "answer": "请先选择已有 task_id，再依据真实任务记录生成报告。",
                "requires_continue_confirmation": False,
            }
        return None

    def _persist_consultation(
        self,
        *,
        intent: str,
        question: str,
        answer: str,
        source: str,
        task_id: str,
        record: dict[str, Any] | None,
        created_at: str,
    ) -> dict[str, Any]:
        if task_id:
            record = self.repository.get(task_id) or record
        consultation_id = f"consult-{uuid.uuid4().hex[:12]}"
        workflow_status = str((record or {}).get("workflow_status", ""))
        value = {
            "schema_version": "consultation-v1",
            "consultation_id": consultation_id,
            "task_id": task_id,
            "intent": intent,
            "question": question,
            "answer": answer,
            "answer_source": source,
            "paused_stage": str((record or {}).get("stage", "")),
            "requires_continue_confirmation": bool(record),
            "continued": False,
            "created_at": created_at,
        }
        if record:
            history = [
                dict(item)
                for item in record.get("consultation_history", [])
                if isinstance(item, dict)
            ]
            history.append(value)
            self.repository.update(task_id, {
                "consultation_history": history[-100:],
                "active_consultation": value,
                "consultation_pause_requested": workflow_status in {
                    "queued", "running", "resuming"
                },
                "consultation_pending_continue": True,
                "workflow_status_before_consultation": workflow_status,
            })
        return {**value, "create_workflow": False}

    def _request_pause(
        self,
        task_id: str,
        record: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not task_id or record is None:
            return record
        workflow_status = str(record.get("workflow_status", ""))
        active = workflow_status in {"queued", "running", "resuming"}
        changes = {
            "consultation_pause_requested": active,
            "consultation_pending_continue": False,
            "workflow_status_before_consultation": workflow_status,
            "message": "正在回答用户咨询；活动工作流将在当前节点边界暂停。",
        }
        return self.repository.update(task_id, changes)

    def attach_report(
        self,
        task_id: str,
        consultation_id: str,
        report: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach generated report metadata to the matching consultation."""
        record = self.repository.get(task_id)
        if record is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        history = [
            dict(item)
            for item in record.get("consultation_history", [])
            if isinstance(item, dict)
        ]
        active = dict(record.get("active_consultation", {}))
        for item in history:
            if item.get("consultation_id") == consultation_id:
                item["report"] = report
                item["answer"] = "任务报告已按持久化科研记录生成。缺失数据在报告中明确标记为未获得。"
        if active.get("consultation_id") == consultation_id:
            active["report"] = report
            active["answer"] = "任务报告已按持久化科研记录生成。缺失数据在报告中明确标记为未获得。"
        self.repository.update(task_id, {
            "consultation_history": history,
            "active_consultation": active,
            "latest_report": report,
        })
        return next(
            (item for item in history if item.get("consultation_id") == consultation_id),
            active,
        )

    def classify(self, question: str, record: dict[str, Any] | None = None) -> str:
        # A separate K3 classification request doubled the latency for every free-form question.
        # Safety-critical workflow commands are covered by deterministic routing; K3 answers once.
        return self._rule_intent(question, bool(record))

    def _answer(
        self,
        intent: str,
        question: str,
        context: dict[str, Any],
    ) -> tuple[str, str]:
        if intent == "report_request":
            return self._fallback_answer(intent, question, context), "local_rules"
        if self.llm.available:
            try:
                answer = self.llm.chat(
                    self._answer_messages(intent, question, context),
                    max_tokens=8192,
                    timeout_seconds=180,
                )
                if not answer.strip():
                    raise LLMError("Kimi returned an empty final answer")
                return answer, "kimi"
            except LLMError as error:
                fallback = self._fallback_answer(intent, question, context)
                return f"{fallback}\n\nKimi 暂不可用：{self._safe_error(error)}", "local_fallback"
        return self._fallback_answer(intent, question, context), "local_rules"

    def _answer_messages(
        self, intent: str, question: str, context: dict[str, Any]
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self._system_prompt(intent)},
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\nRead-only task context:\n"
                    f"{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
                ),
            },
        ]

    def normalize_history_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Recover legacy empty Kimi records without claiming Kimi supplied fallback text."""

        normalized = dict(item)
        if (
            normalized.get("answer_source") == "kimi"
            and not str(normalized.get("answer", "")).strip()
        ):
            intent = str(normalized.get("intent", "general_research_chat"))
            question = str(normalized.get("question", ""))
            normalized["answer"] = self._fallback_answer(intent, question, {})
            normalized["answer_source"] = "local_fallback"
            normalized["answer_recovery_note"] = (
                "The historical Kimi response was empty; a local explanation is shown instead."
            )
        return normalized

    def _system_prompt(self, intent: str) -> str:
        role = {
            "vasp_consultation": (
                "You are a senior VASP and electrocatalysis adviser. Inspect only "
                "text supplied by the user or task context. Separate observed settings, general "
                "advice, convergence-test-dependent choices, and prohibited changes. Never modify "
                "POSCAR, issue shell commands, or claim convergence. End with a copyable natural-"
                "language revision request, but state that deterministic validation and a second "
                "human approval are mandatory."
            ),
            "scientific_explanation": (
                "You are a master-level teacher in electrocatalysis and first-"
                "principles calculations. Explain concept, formula, variables and units, task "
                "interpretation, assumptions, limitations, and relationship to the next stage. "
                "The implemented end-to-end example specializes in high-entropy alloys."
            ),
            "report_request": (
                "Explain what a task report can include. Do not invent results missing from context."
            ),
            "general_research_chat": (
                "Answer as an electrocatalysis research assistant. The currently implemented "
                "deterministic end-to-end workflow uses high-entropy alloy electrocatalysts as "
                "its complete example. Label statements as "
                "task result, project rule, reviewed evidence, general knowledge, or suggestion."
            ),
            "workflow_command": (
                "Explain how the requested operation maps to the current workflow stage. Do not "
                "execute, skip, approve, or mutate a stage. Direct the user to the applicable "
                "human review card and state which deterministic checks remain mandatory."
            ),
        }.get(intent, "Answer conservatively as a scientific research assistant.")
        scope = (
            "Catalyst Agent serves electrocatalyst research broadly, but its currently implemented "
            "deterministic end-to-end modeling workflow is the high-entropy-alloy example. For "
            "other material families, provide scientific explanation or a proposed plan only; "
            "never claim that an unsupported workflow or calculation has run."
        )
        return (
            f"{role}\n\n{scope}\n\n{SCIENTIFIC_RULES}\n"
            "Do not continue or alter the workflow yourself."
        )

    @staticmethod
    def _rule_intent(question: str, has_task: bool) -> str:
        lower = question.lower()
        if any(term in lower for term in ("报告", "总结本次", "生成报告", "report")):
            return "report_request"
        if any(term in lower for term in (
            "incar", "kpoints", "potcar", "encut", "ediff", "ibrion", "nsw",
            "ismear", "sigma", "slurm参数", "vasp参数",
        )):
            return "vasp_consultation"
        if any(term in lower for term in (
            "是什么", "什么意思", "为什么", "如何理解", "公式", "概念", "解释",
            "形成能", "吸附能", "delta", "omega", "固溶体判据", "what is",
        )):
            return "scientific_explanation"
        if re.search(r"(请|帮我|我要|开始|继续|执行|生成|构建|提交).{0,20}(检索|设计|构建|建模|预测|计算|上传|提交|恢复)", question, re.I):
            return "workflow_command"
        return "general_research_chat" if has_task else "general_research_chat"

    @staticmethod
    def _fallback_answer(intent: str, question: str, context: dict[str, Any]) -> str:
        if intent == "scientific_explanation":
            if "吸附能" in question:
                return (
                    "吸附能衡量吸附体系相对于 clean slab 与参考物的能量变化：\n\n"
                    "`E_ads = E_slab+adsorbate - E_clean_slab - E_reference`\n\n"
                    "单位通常为 eV。三项能量必须采用一致的泛函和参数；负值通常表示相对"
                    "所选参考态吸附放热，但不能仅凭一个吸附能判断催化活性。"
                )
            if "形成能" in question:
                return (
                    "形成能描述材料相对于组成元素参考态形成时的能量变化，项目中以 "
                    "eV/atom 表示。CGCNN 值用于低成本预筛，不等同于 DFT 结果，也不能单独"
                    "证明实验相稳定。"
                )
            return (
                "项目的固溶体预筛组合使用形成能与 δ/Ω 描述符。δ 描述原子尺寸失配，"
                "Ω 综合混合熵、平均熔点和混合焓。它们是经验预筛，不是相稳定性的最终证明。"
            )
        if intent == "vasp_consultation":
            return (
                "可以讨论 INCAR、KPOINTS、POTCAR 标签和 vasp.slurm 的受控参数。"
                "ENCUT、k 点密度、EDIFF、EDIFFG、ISMEAR/SIGMA、NSW 等应通过收敛性测试确定。"
                "POSCAR 和原子坐标不能由咨询回答直接修改；采用建议后仍需白名单校验和二次人工批准。"
            )
        if intent == "report_request":
            return "可以依据当前 task_id 生成确定性报告；缺失的结构或能量会明确标记为不可用。"
        stage = context.get("stage_label", "当前任务")
        return f"我已结合只读任务上下文回答。当前阶段为：{stage}。该回答不会修改工作流。"

    @staticmethod
    def _safe_context(record: dict[str, Any] | None) -> dict[str, Any]:
        if not record:
            return {}
        timeline = record.get("workflow_timeline", [])
        completed = [
            {
                "stage_id": item.get("stage_id"),
                "summary": item.get("summary"),
                "outputs": WorkflowConsultationService._compact_outputs(
                    item.get("outputs", {})
                ),
            }
            for item in timeline
            if isinstance(item, dict) and item.get("status") == "completed"
        ]
        return {
            "task_id": record.get("task_id"),
            "question": record.get("question"),
            "workflow_status": record.get("workflow_status"),
            "stage": record.get("stage"),
            "stage_label": record.get("stage_label"),
            "stage_summary": record.get("stage_summary"),
            "completed_stages": completed[-12:],
            "active_slurm_jobs": record.get("active_slurm_jobs", []),
        }

    @staticmethod
    def _compact_outputs(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, (str, int, float, bool)) or item is None:
                compact[str(key)] = item
            elif isinstance(item, list):
                compact[f"{key}_count"] = len(item)
        return dict(list(compact.items())[:12])

    @staticmethod
    def _safe_error(error: Exception) -> str:
        return re.sub(r"(?:sk-|Bearer\s+)[A-Za-z0-9._-]+", "[redacted]", str(error))[:300]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
