from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domain.cluster_transport import ClusterTransport
from app.domain.remote_upload import RemoteUploadSettings
from app.domain.slurm_monitor import SlurmMonitorService
from app.domain.submitted_job_repository import SubmittedJobRepository
from app.domain.vasp_completion import VaspCompletionService


class JobMonitorFacade:
    LOG_FILES = {"OUTCAR", "OSZICAR", "vasp.out", "slurm.out", "key"}

    def __init__(self) -> None:
        self.repository = SubmittedJobRepository()
        self.transport = ClusterTransport()
        self.remote_root = RemoteUploadSettings.from_environment().remote_runs_root

    def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return [self._safe(record) for record in self.repository.list_records() if str(record.get("task_id", "")) == task_id]

    def get(self, slurm_job_id: str) -> dict[str, Any]:
        record = self.repository.get(slurm_job_id)
        if record is None:
            raise FileNotFoundError(f"Unknown Slurm job ID: {slurm_job_id}")
        return self._safe(record)

    def refresh(self, slurm_job_id: str) -> dict[str, Any]:
        if self.repository.get(slurm_job_id) is None:
            raise FileNotFoundError(f"Unknown Slurm job ID: {slurm_job_id}")
        result = SlurmMonitorService(repository=self.repository, transport=self.transport).poll([slurm_job_id])
        jobs = result.get("jobs", [])
        if jobs and (jobs[0].get("terminal") or jobs[0].get("scheduler_state") == "COMPLETED"):
            inspected = VaspCompletionService(repository=self.repository, transport=self.transport, remote_runs_root=self.remote_root).inspect([slurm_job_id])
            jobs = inspected.get("jobs", jobs)
        if not jobs:
            errors = result.get("errors", [])
            raise RuntimeError(str(errors[0].get("message", "Unable to refresh job.")) if errors else "Unable to refresh job.")
        return self._safe(jobs[0])

    def logs(self, slurm_job_id: str, name: str = "OUTCAR") -> dict[str, Any]:
        record = self.repository.get(slurm_job_id)
        if record is None:
            raise FileNotFoundError(f"Unknown Slurm job ID: {slurm_job_id}")
        normalized = name.strip()
        if normalized == "key":
            return self._key_logs(slurm_job_id, record)
        if normalized == "slurm.out":
            normalized = f"slurm-{slurm_job_id}.out"
        if normalized.startswith("slurm-") and normalized.endswith(".out"):
            normalized = f"slurm-{slurm_job_id}.out"
        elif normalized not in self.LOG_FILES:
            raise ValueError("Unsupported log file.")
        directory = self.transport.validate_remote_child(str(record["remote_job_directory"]), self.remote_root)
        command = f"cd {self.transport.quote(directory)} && tail -n 160 -- {self.transport.quote(normalized)} 2>/dev/null || true"
        content = self.transport.run(command, timeout=45)
        return {
            "slurm_job_id": slurm_job_id,
            "name": normalized,
            "content": content[-40_000:],
            "read_at": datetime.now(timezone.utc).isoformat(),
        }

    def _key_logs(
        self,
        slurm_job_id: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        directory = self.transport.validate_remote_child(
            str(record["remote_job_directory"]), self.remote_root
        )
        slurm_name = f"slurm-{slurm_job_id}.out"
        command = (
            f"cd {self.transport.quote(directory)} && "
            "for f in OSZICAR OUTCAR vasp.out "
            f"{self.transport.quote(slurm_name)}; do "
            "if [ -f \"$f\" ]; then "
            "printf '\\n===== %s =====\\n' \"$f\"; tail -n 120 -- \"$f\"; "
            "fi; done"
        )
        content = self.transport.run(command, timeout=45)
        return {
            "slurm_job_id": slurm_job_id,
            "name": "关键日志",
            "content": content[-80_000:],
            "read_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _safe(record: dict[str, Any]) -> dict[str, Any]:
        parsed = record.get("parsed_vasp_result", {}) if isinstance(record.get("parsed_vasp_result"), dict) else {}
        return {
            "slurm_job_id": str(record.get("slurm_job_id", "")),
            "task_id": str(record.get("task_id", "")),
            "job_id": str(record.get("job_id", "")),
            "job_source": str(record.get("job_source", "")),
            "scheduler_state": str(record.get("scheduler_state", "UNKNOWN")),
            "scheduler_elapsed": record.get("scheduler_elapsed"),
            "scheduler_detail": record.get("scheduler_detail"),
            "monitoring_status": str(record.get("monitoring_status", "")),
            "terminal": bool(record.get("terminal", False)),
            "last_polled_at": record.get("last_polled_at"),
            "vasp_decision": str(record.get("vasp_decision", "not_checked")),
            "vasp_ionic_steps": record.get("vasp_ionic_steps", parsed.get("ionic_step_count")),
            "final_toten_ev": parsed.get("final_toten_ev"),
            "max_force_ev_ang": parsed.get("max_force_ev_ang"),
            "download_eligible": bool(record.get("download_eligible", False)),
        }
