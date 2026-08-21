from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from dotenv import load_dotenv

from app.domain.cluster_readonly_preflight import (
    ClusterReadonlySettings,
)
from app.domain.remote_execution_plan import (
    RemoteExecutionPlanService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


class RemoteSubmissionError(RuntimeError):
    """A submission failed before a valid Slurm ID was received."""


class RemoteSubmissionUnknown(RuntimeError):
    """The client cannot determine whether Slurm accepted the job."""


@dataclass(frozen=True)
class RemoteSubmissionSettings:
    enabled: bool
    timeout_seconds: int
    remote_runs_root: str
    slurm_script_name: str
    ssh: ClusterReadonlySettings

    @classmethod
    def from_environment(
        cls,
    ) -> "RemoteSubmissionSettings":
        enabled = os.getenv(
            "CLUSTER_SUBMISSION_ENABLED",
            "false",
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        return cls(
            enabled=enabled,
            timeout_seconds=int(
                os.getenv(
                    "CLUSTER_REMOTE_OPERATION_TIMEOUT_SECONDS",
                    "120",
                )
            ),
            remote_runs_root=os.getenv(
                "CLUSTER_REMOTE_RUNS_ROOT",
                "",
            ).strip().rstrip("/"),
            slurm_script_name=os.getenv(
                "CLUSTER_SLURM_SCRIPT_NAME",
                "vasp.slurm",
            ).strip(),
            ssh=ClusterReadonlySettings.from_environment(),
        )


class RemoteSubmissionService:
    """Submit remotely verified VASP jobs exactly once."""

    FILE_NAMES = {
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "POTCAR",
        "vasp.slurm",
    }

    SAFE_REMOTE_PATH = re.compile(
        r"^/[A-Za-z0-9._/+:-]+$"
    )

    SAFE_SCRIPT_NAME = re.compile(
        r"^[A-Za-z0-9._-]+$"
    )

    SHA256_PATTERN = re.compile(
        r"^[0-9a-fA-F]{64}$"
    )

    def __init__(
        self,
        settings: RemoteSubmissionSettings | None = None,
    ) -> None:
        self.settings = (
            settings
            or RemoteSubmissionSettings.from_environment()
        )

    def submit(
        self,
        plan: dict[str, Any],
        verified_jobs: list[dict[str, Any]],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_inputs(
            plan=plan,
            verified_jobs=verified_jobs,
            review=review,
        )

        approved_ids = list(
            review.get("approved_job_ids", [])
        )

        if not self.settings.enabled:
            return self._result(
                status="remote_submission_disabled",
                jobs=[],
                approved_count=len(approved_ids),
                errors=[{
                    "check": "submission_enabled",
                    "message": (
                        "CLUSTER_SUBMISSION_ENABLED is false"
                    ),
                }],
            )

        jobs_by_id = {
            str(job.get("job_id", "")): job
            for job in verified_jobs
        }

        results: list[dict[str, Any]] = []

        for job_id in approved_ids:
            result = self._submit_one(
                jobs_by_id[job_id]
            )
            results.append(result)

            # An ambiguous result must never be retried automatically.
            if (
                result.get("submission_status")
                == "submission_unknown"
            ):
                break

        attempted_ids = {
            str(job.get("job_id", ""))
            for job in results
        }

        for job_id in approved_ids:
            if job_id not in attempted_ids:
                results.append({
                    **jobs_by_id[job_id],
                    "submission_status": (
                        "submission_not_attempted"
                    ),
                    "submission_approved": True,
                    "submission_performed": False,
                    "slurm_job_id": None,
                    "errors": [{
                        "job_id": job_id,
                        "error_type": "SubmissionStopped",
                        "message": (
                            "Submission stopped after an "
                            "ambiguous previous result."
                        ),
                    }],
                })

        submitted = [
            job
            for job in results
            if job.get("submission_status")
            == "submitted"
        ]

        unknown = [
            job
            for job in results
            if job.get("submission_status")
            == "submission_unknown"
        ]

        failed = [
            job
            for job in results
            if job.get("submission_status") in {
                "submission_failed",
                "submission_not_attempted",
            }
        ]

        if len(submitted) == len(approved_ids):
            status = "remote_submission_completed"
        elif unknown and not submitted:
            status = "remote_submission_unknown"
        elif submitted:
            status = "remote_submission_partial"
        else:
            status = "remote_submission_failed"

        errors = [
            error
            for job in results
            for error in job.get("errors", [])
        ]

        return self._result(
            status=status,
            jobs=results,
            approved_count=len(approved_ids),
            submitted_jobs=submitted,
            unknown_count=len(unknown),
            failed_count=len(failed),
            errors=errors,
        )

    def _validate_inputs(
        self,
        plan: dict[str, Any],
        verified_jobs: list[dict[str, Any]],
        review: dict[str, Any],
    ) -> None:
        if not isinstance(plan, dict):
            raise TypeError(
                "plan must be a dictionary"
            )

        if (
            plan.get("status")
            != "remote_execution_plan_ready"
        ):
            raise ValueError(
                "Remote execution plan is not ready"
            )

        if not isinstance(verified_jobs, list):
            raise TypeError(
                "verified_jobs must be a list"
            )

        if not isinstance(review, dict):
            raise TypeError(
                "review must be a dictionary"
            )

        if (
            review.get("status")
            != "remote_submission_approved"
        ):
            raise ValueError(
                "Remote submission is not approved"
            )

        plan_digest = str(
            plan.get("plan_digest", "")
        )

        recalculated_digest = (
            RemoteExecutionPlanService._plan_digest(
                task_id=str(plan.get("task_id", "")),
                job_source=str(
                    plan.get("job_source", "")
                ),
                batch_directory=str(
                    plan.get(
                        "remote_batch_directory",
                        "",
                    )
                ),
                jobs=[
                    job
                    for job in plan.get("jobs", [])
                    if isinstance(job, dict)
                ],
            )
        )

        if recalculated_digest != plan_digest:
            raise ValueError(
                "Remote execution plan changed "
                "after approval"
            )

        if (
            review.get("plan_digest")
            != plan_digest
        ):
            raise ValueError(
                "Submission approval digest mismatch"
            )

        expected_phrase = (
            f"SUBMIT {plan.get('task_id', '')}"
        )

        if (
            review.get("confirmation_text")
            != expected_phrase
        ):
            raise ValueError(
                "Submission confirmation text "
                "does not match"
            )

        approved_ids = review.get(
            "approved_job_ids",
            [],
        )

        if (
            not isinstance(approved_ids, list)
            or not approved_ids
        ):
            raise ValueError(
                "At least one approved job is required"
            )

        if len(approved_ids) != len(set(approved_ids)):
            raise ValueError(
                "approved_job_ids contains duplicates"
            )

        planned_jobs = {
            str(job.get("job_id", "")): job
            for job in plan.get("jobs", [])
            if isinstance(job, dict)
        }

        verified_by_id = {
            str(job.get("job_id", "")): job
            for job in verified_jobs
            if isinstance(job, dict)
        }

        unknown_ids = (
            set(approved_ids)
            - set(verified_by_id)
        )

        if unknown_ids:
            raise ValueError(
                "Unknown or unverified job IDs: "
                + ", ".join(sorted(unknown_ids))
            )

        for job_id in approved_ids:
            verified = verified_by_id[job_id]
            planned = planned_jobs.get(job_id)

            if not planned:
                raise ValueError(
                    f"Job is missing from plan: {job_id}"
                )

            if not verified.get(
                "remote_hash_verified"
            ):
                raise ValueError(
                    f"Remote hashes are not verified: "
                    f"{job_id}"
                )

            if (
                verified.get("remote_job_directory")
                != planned.get(
                    "remote_job_directory"
                )
            ):
                raise ValueError(
                    "Remote job directory changed "
                    "after upload"
                )

            self._validate_file_manifest(
                planned=planned,
                verified=verified,
            )

    def _validate_file_manifest(
        self,
        planned: dict[str, Any],
        verified: dict[str, Any],
    ) -> None:
        planned_files = {
            str(item.get("name", "")): (
                str(item.get("sha256", "")),
                int(item.get("size_bytes", 0)),
            )
            for item in planned.get("files", [])
        }

        verified_files = {
            str(item.get("name", "")): (
                str(item.get("sha256", "")),
                int(item.get("size_bytes", 0)),
            )
            for item in verified.get("files", [])
        }

        if set(planned_files) != self.FILE_NAMES:
            raise ValueError(
                "Planned job does not contain "
                "exactly five VASP files"
            )

        if verified_files != planned_files:
            raise ValueError(
                "Verified file manifest changed "
                "after upload"
            )

    def _submit_one(
        self,
        job: dict[str, Any],
    ) -> dict[str, Any]:
        result = {
            **job,
            "submission_approved": True,
            "submission_performed": False,
            "submission_status": (
                "submission_failed"
            ),
            "slurm_job_id": None,
            "submitted_at": None,
            "errors": [],
        }

        try:
            remote_directory = str(
                job.get(
                    "remote_job_directory",
                    "",
                )
            )

            self._validate_remote_directory(
                remote_directory
            )

            output = self._run_submission_command(
                job
            )

            job_id = self._parse_slurm_job_id(
                output
            )

            result.update({
                "submission_performed": True,
                "submission_status": "submitted",
                "slurm_job_id": job_id,
                "submitted_at": (
                    datetime.now(timezone.utc)
                    .isoformat()
                ),
            })

        except RemoteSubmissionUnknown as error:
            result["submission_status"] = (
                "submission_unknown"
            )
            result["errors"].append({
                "job_id": job.get("job_id"),
                "error_type": type(error).__name__,
                "message": str(error),
                "manual_reconciliation_required": True,
            })

        except Exception as error:
            result["submission_status"] = (
                "submission_failed"
            )
            result["errors"].append({
                "job_id": job.get("job_id"),
                "error_type": type(error).__name__,
                "message": str(error),
            })

        return result

    def _run_submission_command(
        self,
        job: dict[str, Any],
    ) -> str:
        remote_directory = str(
            job["remote_job_directory"]
        )

        script_name = (
            self.settings.slurm_script_name
        )

        if (
            not self.SAFE_SCRIPT_NAME.fullmatch(
                script_name
            )
            or script_name != "vasp.slurm"
        ):
            raise ValueError(
                "Unsafe Slurm script name"
            )

        file_items = sorted(
            job.get("files", []),
            key=lambda item: str(
                item.get("name", "")
            ),
        )

        hash_lines = []

        for item in file_items:
            name = str(item.get("name", ""))
            digest = str(item.get("sha256", ""))

            if (
                name not in self.FILE_NAMES
                or not self.SHA256_PATTERN.fullmatch(
                    digest
                )
            ):
                raise ValueError(
                    "Invalid remote file manifest"
                )

            hash_lines.append(
                f"{digest.lower()}  {name}"
            )

        hash_payload = "\n".join(hash_lines)

        file_checks = [
            f"test -s {shlex.quote(name)}"
            for name in sorted(self.FILE_NAMES)
        ]

        command_parts = [
            f"cd {shlex.quote(remote_directory)}",
            (
                'test "$(find . -mindepth 1 '
                '-maxdepth 1 | wc -l)" -eq 5'
            ),
            *file_checks,
            (
                "printf '%s\\n' "
                f"{shlex.quote(hash_payload)} "
                "| sha256sum --check --status"
            ),
            (
                "sbatch --parsable "
                f"{shlex.quote(script_name)}"
            ),
        ]

        remote_command = " && ".join(
            command_parts
        )

        return self._run_ssh_for_submission(
            remote_command
        )

    def _validate_remote_directory(
        self,
        remote_directory: str,
    ) -> None:
        if not self.SAFE_REMOTE_PATH.fullmatch(
            remote_directory
        ):
            raise ValueError(
                "Unsafe remote job directory"
            )

        root = PurePosixPath(
            self.settings.remote_runs_root
        )
        path = PurePosixPath(remote_directory)

        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(
                "Remote job directory escaped "
                "configured runs root"
            ) from error

        if path == root:
            raise ValueError(
                "Cannot submit from the runs root"
            )

    def _run_ssh_for_submission(
        self,
        remote_command: str,
    ) -> str:
        ssh = shutil.which("ssh")

        if not ssh:
            raise RemoteSubmissionError(
                "Windows OpenSSH ssh was not found"
            )

        command = [
            ssh,
            "-T",
            "-p",
            str(self.settings.ssh.port),
            "-i",
            str(
                self.settings.ssh
                .key_path.resolve()
            ),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            (
                "UserKnownHostsFile="
                f"{self.settings.ssh.known_hosts_path.resolve()}"
            ),
            (
                f"{self.settings.ssh.user}@"
                f"{self.settings.ssh.host}"
            ),
            remote_command,
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RemoteSubmissionUnknown(
                "sbatch timed out; do not retry "
                "until squeue is checked manually"
            ) from error

        if completed.returncode:
            raise RemoteSubmissionUnknown(
                "Remote submission command did not "
                "return cleanly; check squeue before "
                "trying again. "
                f"stderr={completed.stderr.strip()[:500]}"
            )

        return completed.stdout.strip()

    def _parse_slurm_job_id(
        self,
        output: str,
    ) -> str:
        lines = [
            line.strip()
            for line in output.splitlines()
            if line.strip()
        ]

        if len(lines) != 1:
            raise RemoteSubmissionUnknown(
                "Unexpected sbatch output; check "
                "squeue before retrying"
            )

        job_id = lines[0].split(";", 1)[0]

        if not job_id.isdigit():
            raise RemoteSubmissionUnknown(
                "No valid numeric Slurm job ID "
                "was returned"
            )

        return job_id

    def _result(
        self,
        status: str,
        jobs: list[dict[str, Any]],
        approved_count: int,
        errors: list[dict[str, Any]],
        submitted_jobs: (
            list[dict[str, Any]] | None
        ) = None,
        unknown_count: int = 0,
        failed_count: int | None = None,
    ) -> dict[str, Any]:
        submitted = submitted_jobs or []

        return {
            "schema_version": "c11.4.3",
            "stage": "remote_submission",
            "status": status,
            "approved_count": approved_count,
            "submitted_count": len(submitted),
            "unknown_count": unknown_count,
            "failed_count": (
                failed_count
                if failed_count is not None
                else approved_count
            ),
            "jobs": jobs,
            "submitted_jobs": submitted,
            "slurm_job_ids": [
                job.get("slurm_job_id")
                for job in submitted
            ],
            "errors": errors,
            "submission_performed": bool(
                submitted
            ),
            "automatic_retry_allowed": False,
            "next_stage": (
                "c11.5_job_monitoring"
                if submitted
                else None
            ),
        }