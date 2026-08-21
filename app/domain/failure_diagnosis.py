from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.submitted_job_repository import SubmittedJobRepository


class FailureDiagnosisService:
    RULES = (
        ("out_of_memory", ("out of memory", "oom-kill", "oom_kill"),
         "Increase memory or reduce ranks; keep scientific inputs unchanged."),
        ("walltime", ("time limit", "timeout", "due to time limit"),
         "Increase Slurm walltime and restart from the last valid structure."),
        ("electronic_nonconvergence", ("edddav", "zhegv", "not converged"),
         "Review ALGO, mixing and NELM through the existing VASP revision gate."),
        ("ionic_nonconvergence", ("reached nsw", "too many ionic steps"),
         "Review NSW and ionic settings through the existing VASP revision gate."),
        ("node_failure", ("node_fail", "node failure"),
         "Resubmit unchanged inputs after cluster health is restored."),
    )

    def __init__(self, repository: SubmittedJobRepository | None = None):
        self.repository = repository or SubmittedJobRepository()

    def diagnose(self, slurm_job_ids: list[str] | None = None) -> dict[str, Any]:
        records = self.repository.list_records()
        wanted = set(slurm_job_ids or [])
        if wanted:
            records = [r for r in records if r.get("slurm_job_id") in wanted]
        jobs = []
        for record in records:
            diagnosis = self._diagnose_one(record)
            jobs.append(self.repository.update(record["slurm_job_id"], diagnosis))
        return {
            "schema_version": "c11.5.6",
            "stage": "failure_diagnosis",
            "status": "failure_diagnosis_completed" if jobs else "failure_diagnosis_empty",
            "diagnosed_count": len(jobs),
            "retry_candidate_count": sum(j.get("retry_plan", {}).get("eligible", False) for j in jobs),
            "jobs": jobs,
            "automatic_retry_performed": False,
            "next_stage": "human_retry_plan_review",
        }

    def _diagnose_one(self, record: dict[str, Any]) -> dict[str, Any]:
        text = " ".join([
            str(record.get("scheduler_state", "")),
            str(record.get("last_scheduler_message", "")),
            self._read_logs(record),
        ]).lower()
        category = "unknown_failure"
        recommendation = "Inspect OUTCAR and Slurm logs manually before changing inputs."
        matched = []
        for name, markers, advice in self.RULES:
            found = [marker for marker in markers if marker in text]
            if found:
                category, recommendation, matched = name, advice, found
                break
        failed = record.get("vasp_decision") in {
            "failed", "completed_unconverged"
        } or record.get("scheduler_state") in {
            "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED"
        }
        retry_plan = {
            "eligible": bool(failed),
            "source_slurm_job_id": record.get("slurm_job_id"),
            "source_job_id": record.get("job_id"),
            "failure_category": category,
            "recommended_action": recommendation,
            "poscar_change_allowed": False,
            "automatic_submission_allowed": False,
            "required_route": (
                "c12.5_revision_then_c12.6_review"
                if record.get("job_source")
                == "c12_5_adsorption"
                else "c10_or_c6d_revision_then_c11.4_review"
            ),
            "required_confirmation": f"RETRY {record.get('slurm_job_id')}",
        }
        return {
            "failure_diagnosis": {
                "category": category if failed else "not_failed",
                "matched_markers": matched,
                "recommendation": recommendation if failed else "No retry is required.",
                "confidence": "rule_based",
                "diagnosed_at": datetime.now(timezone.utc).isoformat(),
            },
            "retry_plan": retry_plan,
            "automatic_retry_allowed": False,
        }

    @staticmethod
    def _read_logs(record: dict[str, Any]) -> str:
        root_text = str(record.get("local_result_directory", ""))
        if not root_text:
            return ""
        root = Path(root_text)
        values = []
        for name in ("OUTCAR", "slurm.out", "slurm.err"):
            path = root / name
            if path.is_file():
                values.append(path.read_text(encoding="utf-8", errors="replace")[-200000:])
        return "\n".join(values)


class RetryReviewGate:
    """Approve a retry plan without modifying or submitting files."""

    @staticmethod
    def review(record: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        plan = record.get("retry_plan", {})
        if not plan.get("eligible"):
            raise ValueError("This job is not eligible for retry review")
        expected = plan.get("required_confirmation")
        approved = (
            decision.get("action") == "approve_retry_plan"
            and decision.get("confirmation_text") == expected
        )
        return {
            "schema_version": "c11.5.6",
            "stage": "retry_review",
            "status": "retry_plan_approved" if approved else "retry_plan_deferred",
            "source_slurm_job_id": record.get("slurm_job_id"),
            "confirmation_text": decision.get("confirmation_text", ""),
            "approved_retry_plan": plan if approved else None,
            "poscar_modified": False,
            "submission_performed": False,
            "next_stage": "c10_or_c6d_revision" if approved else None,
        }
