from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domain.cluster_transport import ClusterTransport
from app.domain.remote_upload import RemoteUploadSettings
from app.domain.submitted_job_repository import SubmittedJobRepository


class VaspCompletionService:
    def __init__(
        self,
        repository: SubmittedJobRepository | None = None,
        transport: ClusterTransport | None = None,
        remote_runs_root: str | None = None,
    ) -> None:
        self.repository = repository or SubmittedJobRepository()
        self.transport = transport or ClusterTransport()
        self.remote_runs_root = remote_runs_root or RemoteUploadSettings.from_environment().remote_runs_root

    def inspect(self, slurm_job_ids: list[str] | None = None) -> dict[str, Any]:
        records = self.repository.list_records()
        wanted = set(slurm_job_ids or [])
        if wanted:
            records = [r for r in records if r.get("slurm_job_id") in wanted]
        jobs, errors = [], []
        for record in records:
            try:
                snapshot = self._inspect_one(record)
                jobs.append(self.repository.update(record["slurm_job_id"], snapshot))
            except Exception as error:
                errors.append({
                    "slurm_job_id": record.get("slurm_job_id"),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })
        return {
            "schema_version": "c11.5.3",
            "stage": "vasp_completion",
            "status": "vasp_completion_checked" if jobs and not errors else (
                "vasp_completion_partial" if jobs else
                "vasp_completion_empty" if not records else "vasp_completion_failed"
            ),
            "checked_count": len(jobs),
            "completed_count": sum(j.get("vasp_decision") == "completed_converged" for j in jobs),
            "unconverged_count": sum(j.get("vasp_decision") == "completed_unconverged" for j in jobs),
            "failed_count": sum(j.get("vasp_decision") == "failed" for j in jobs),
            "incomplete_count": sum(j.get("vasp_decision") == "incomplete" for j in jobs),
            "jobs": jobs,
            "errors": errors,
            "next_stage": "c11.5.4_result_download_review",
        }

    def _inspect_one(self, record: dict[str, Any]) -> dict[str, Any]:
        directory = self.transport.validate_remote_child(
            str(record["remote_job_directory"]), self.remote_runs_root
        )
        quoted = self.transport.quote(directory)
        command = " && ".join([
            f"cd {quoted}",
            "printf 'outcar=%s\\n' \"$(test -s OUTCAR && echo yes || echo no)\"",
            "printf 'oszicar=%s\\n' \"$(test -s OSZICAR && echo yes || echo no)\"",
            "printf 'contcar=%s\\n' \"$(test -s CONTCAR && echo yes || echo no)\"",
            "printf 'normal=%s\\n' \"$(grep -q 'General timing and accounting informations for this job' OUTCAR 2>/dev/null && echo yes || echo no)\"",
            "printf 'converged=%s\\n' \"$(grep -Eq 'reached required accuracy|aborting loop because EDIFF is reached' OUTCAR 2>/dev/null && echo yes || echo no)\"",
            "printf 'ionic_steps=%s\\n' \"$(grep -c 'F=' OSZICAR 2>/dev/null || true)\"",
        ])
        markers = {}
        for line in self.transport.run(command).splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                markers[key.strip()] = value.strip()
        scheduler = str(record.get("scheduler_state", "UNKNOWN"))
        normal = markers.get("normal") == "yes"
        converged = markers.get("converged") == "yes"
        files_ok = all(markers.get(name) == "yes" for name in ("outcar", "oszicar", "contcar"))
        scheduler_terminal_success = scheduler == "COMPLETED"
        vasp_terminal_success = normal and files_ok
        if (
            (scheduler_terminal_success or vasp_terminal_success)
            and converged
        ):
            decision = "completed_converged"
        elif scheduler_terminal_success or vasp_terminal_success:
            decision = "completed_unconverged"
        elif scheduler in {"FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED"}:
            decision = "failed"
        else:
            decision = "incomplete"
        inferred_from_vasp = (
            vasp_terminal_success and not scheduler_terminal_success
        )
        return {
            "vasp_decision": decision,
            "vasp_normal_termination": normal,
            "vasp_converged_marker": converged,
            "vasp_required_outputs_present": files_ok,
            "vasp_ionic_steps": int(markers.get("ionic_steps", "0") or 0),
            "vasp_markers": markers,
            "completion_checked_at": datetime.now(timezone.utc).isoformat(),
            "download_eligible": decision in {
                "completed_converged", "completed_unconverged", "failed"
            },
            "scheduler_completion_inferred_from_vasp": inferred_from_vasp,
            **({
                "scheduler_state": "COMPLETED",
                "monitoring_status": "scheduler_completed_inferred",
                "terminal": True,
                "scheduler_source": "vasp_normal_termination",
                "last_scheduler_message": (
                    "Slurm history was unavailable; completion was inferred "
                    "from normal VASP termination and required output files."
                ),
            } if inferred_from_vasp else {}),
        }
