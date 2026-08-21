from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domain.cluster_transport import ClusterTransport
from app.domain.cluster_transport import ClusterTransportError
from app.domain.submitted_job_repository import SubmittedJobRepository


class SlurmMonitorService:
    QUERY_TIMEOUT_SECONDS = 45
    ACTIVE = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED"}
    SUCCESS = {"COMPLETED"}
    FAILURE = {
        "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY",
        "PREEMPTED", "BOOT_FAIL", "DEADLINE", "REVOKED",
    }

    def __init__(
        self,
        repository: SubmittedJobRepository | None = None,
        transport: ClusterTransport | None = None,
    ) -> None:
        self.repository = repository or SubmittedJobRepository()
        self.transport = transport or ClusterTransport()

    def poll(self, slurm_job_ids: list[str] | None = None) -> dict[str, Any]:
        records = self.repository.list_records()
        wanted = set(slurm_job_ids or [])
        if wanted:
            records = [r for r in records if r.get("slurm_job_id") in wanted]
        results, errors = [], []
        for record in records:
            try:
                snapshot = self._poll_one(record)
                updated = self.repository.update(record["slurm_job_id"], snapshot)
                results.append(updated)
            except Exception as error:
                errors.append({
                    "slurm_job_id": record.get("slurm_job_id"),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })
        status = "slurm_monitor_completed" if results and not errors else (
            "slurm_monitor_partial" if results else
            "slurm_monitor_empty" if not records else "slurm_monitor_failed"
        )
        return {
            "schema_version": "c11.5.2",
            "stage": "slurm_monitor",
            "status": status,
            "polled_count": len(results),
            "failed_count": len(errors),
            "jobs": results,
            "errors": errors,
            "next_stage": "c11.5.3_vasp_completion_check",
        }

    def _poll_one(self, record: dict[str, Any]) -> dict[str, Any]:
        job_id = str(record["slurm_job_id"])
        if not job_id.isdigit():
            raise ValueError("Invalid persisted Slurm job ID")
        try:
            queue = self.transport.run(
                f"squeue -h -j {job_id} -o '%T|%M|%R'",
                timeout=self.QUERY_TIMEOUT_SECONDS,
            )
        except ClusterTransportError as error:
            if "Invalid job id" not in str(error):
                raise
            # Some clusters return an error instead of an empty squeue
            # result after a completed job leaves the live queue.
            queue = ""
        source = "squeue"
        raw = queue.splitlines()[0].strip() if queue.strip() else ""
        if not raw:
            source = "sacct"
            accounting = self.transport.run(
                f"sacct -n -X -j {job_id} --format=State,Elapsed,ExitCode -P",
                timeout=self.QUERY_TIMEOUT_SECONDS,
            )
            raw = (
                accounting.splitlines()[0].strip()
                if accounting.strip()
                else ""
            )
        parts = [part.strip() for part in raw.split("|")] if raw else []
        state = self._normalize_state(parts[0] if parts else "UNKNOWN")
        terminal = state in self.SUCCESS | self.FAILURE
        monitoring = (
            "scheduler_active" if state in self.ACTIVE else
            "scheduler_completed" if state in self.SUCCESS else
            "scheduler_failed" if state in self.FAILURE else
            "scheduler_unknown"
        )
        return {
            "scheduler_state": state,
            "monitoring_status": monitoring,
            "terminal": terminal,
            "scheduler_source": source,
            "scheduler_elapsed": parts[1] if len(parts) > 1 else None,
            "scheduler_detail": parts[2] if len(parts) > 2 else None,
            "last_polled_at": datetime.now(timezone.utc).isoformat(),
            "last_scheduler_message": raw or "No squeue/sacct record found",
        }

    @staticmethod
    def _normalize_state(value: str) -> str:
        return value.strip().upper().split()[0].split("+")[0] if value.strip() else "UNKNOWN"
