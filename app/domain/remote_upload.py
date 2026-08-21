from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
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


class RemoteUploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteUploadSettings:
    enabled: bool
    timeout_seconds: int
    remote_runs_root: str
    ssh: ClusterReadonlySettings
    retry_attempts: int = 3
    retry_delay_seconds: float = 2.0

    @classmethod
    def from_environment(
        cls,
    ) -> "RemoteUploadSettings":
        enabled = os.getenv(
            "CLUSTER_REMOTE_WRITE_ENABLED",
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
            ssh=(
                ClusterReadonlySettings
                .from_environment()
            ),
            retry_attempts=max(1, int(os.getenv(
                "CLUSTER_REMOTE_RETRY_ATTEMPTS", "3"
            ))),
            retry_delay_seconds=max(0.0, float(os.getenv(
                "CLUSTER_REMOTE_RETRY_DELAY_SECONDS", "2"
            ))),
        )


class RemoteUploadService:
    """Upload approved jobs and verify remote SHA-256."""

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

    def __init__(
        self,
        settings: RemoteUploadSettings | None = None,
    ) -> None:
        self.settings = (
            settings
            or RemoteUploadSettings.from_environment()
        )

    def upload(
        self,
        plan: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_inputs(plan, review)

        approved_ids = list(
            review.get("approved_job_ids", [])
        )

        if not self.settings.enabled:
            return self._result(
                status="remote_upload_disabled",
                jobs=[],
                approved_count=len(approved_ids),
                errors=[{
                    "check": "remote_write_enabled",
                    "message": (
                        "CLUSTER_REMOTE_WRITE_ENABLED "
                        "is false"
                    ),
                }],
            )

        jobs_by_id = {
            str(job.get("job_id", "")): job
            for job in plan.get("jobs", [])
            if isinstance(job, dict)
        }

        results = []

        for job_id in approved_ids:
            results.append(
                self._upload_one(
                    jobs_by_id[job_id]
                )
            )

        verified_jobs = [
            job
            for job in results
            if job.get("remote_hash_verified")
        ]

        failed_jobs = [
            job
            for job in results
            if not job.get("remote_hash_verified")
        ]

        if len(verified_jobs) == len(results):
            status = "remote_upload_verified"
        elif verified_jobs:
            status = "remote_upload_partial"
        else:
            status = "remote_upload_failed"

        errors = [
            error
            for job in failed_jobs
            for error in job.get("errors", [])
        ]

        return self._result(
            status=status,
            jobs=results,
            approved_count=len(approved_ids),
            verified_jobs=verified_jobs,
            errors=errors,
        )

    def _validate_inputs(
        self,
        plan: dict[str, Any],
        review: dict[str, Any],
    ) -> None:
        if not isinstance(plan, dict):
            raise TypeError("plan must be a dictionary")

        if not isinstance(review, dict):
            raise TypeError("review must be a dictionary")

        if (
            plan.get("status")
            != "remote_execution_plan_ready"
        ):
            raise ValueError(
                "Remote execution plan is not ready"
            )

        if (
            review.get("status")
            != "remote_upload_approved"
        ):
            raise ValueError(
                "Remote upload was not approved"
            )

        plan_digest = str(
            plan.get("plan_digest", "")
        )
        reviewed_digest = str(
            review.get("plan_digest", "")
        )

        if (
            not plan_digest
            or reviewed_digest != plan_digest
        ):
            raise ValueError(
                "Approved plan digest does not match"
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
                "Remote execution plan changed after approval"
            )

        expected_phrase = (
            f"UPLOAD {plan.get('task_id', '')}"
        )

        if (
            review.get("confirmation_text")
            != expected_phrase
        ):
            raise ValueError(
                "Upload confirmation text does not match"
            )

        planned_ids = {
            str(job.get("job_id", ""))
            for job in plan.get("jobs", [])
        }

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

        unknown = set(approved_ids) - planned_ids

        if unknown:
            raise ValueError(
                "Unknown approved job IDs: "
                + ", ".join(sorted(unknown))
            )

    def _upload_one(
        self,
        job: dict[str, Any],
    ) -> dict[str, Any]:
        job_id = str(job.get("job_id", ""))
        final_directory = str(
            job.get("remote_job_directory", "")
        )
        staging_directory = ""

        result = {
            **job,
            "staging_directory": staging_directory,
            "remote_write_performed": False,
            "upload_performed": False,
            "remote_hash_verified": False,
            "submission_performed": False,
            "errors": [],
        }

        try:
            self._validate_remote_directory(
                final_directory
            )
            self._validate_local_files(job)

            remote_state = self._discover_remote_state(final_directory)
            if remote_state["kind"] == "final":
                hashes = self._remote_hashes(final_directory)
                self._validate_expected_hashes(job, hashes)
                result["staging_directory"] = ""
                result["remote_hash_verified"] = True
                result["upload_status"] = "existing_remote_verified"
                result["reused_existing_upload"] = True
                return result

            staging_directory = str(remote_state.get("path", ""))
            if not staging_directory:
                staging_directory = (
                    f"{final_directory}.uploading-"
                    f"{uuid.uuid4().hex[:12]}"
                )
                self._validate_remote_directory(staging_directory)
                self._prepare_staging_directory(
                    final_directory,
                    staging_directory,
                )
                result["remote_write_performed"] = True
            else:
                self._validate_remote_directory(staging_directory)
                result["resumed_staging_upload"] = True

            result["staging_directory"] = staging_directory
            existing_hashes = self._remote_hashes(
                staging_directory,
                require_complete=False,
            )
            files_to_upload = [
                file for file in job.get("files", [])
                if existing_hashes.get(str(file["name"]))
                != str(file["sha256"])
            ]
            if files_to_upload:
                self._upload_files(
                    local_paths=[
                        Path(str(file["local_path"]))
                        for file in files_to_upload
                    ],
                    remote_directory=staging_directory,
                )
                result["upload_performed"] = True
                result["remote_write_performed"] = True
            result["uploaded_file_names"] = [
                str(file["name"]) for file in files_to_upload
            ]
            result["reused_file_names"] = sorted(
                self.FILE_NAMES - set(result["uploaded_file_names"])
            )

            remote_hashes = self._remote_hashes(
                staging_directory
            )

            self._validate_expected_hashes(job, remote_hashes)

            finalize_command = (
                f"test ! -e "
                f"{shlex.quote(final_directory)}"
                " && "
                f"mv {shlex.quote(staging_directory)} "
                f"{shlex.quote(final_directory)}"
            )

            self._run_ssh(
                finalize_command,
                "finalize verified remote directory",
            )

            result["remote_hash_verified"] = True
            result["remote_job_directory"] = (
                final_directory
            )
            result["upload_status"] = (
                "uploaded_and_verified"
            )

        except Exception as error:
            result["upload_status"] = "upload_failed"
            result["errors"].append({
                "job_id": job_id,
                "error_type": type(error).__name__,
                "message": str(error),
                "staging_directory": staging_directory,
            })

        return result

    def _discover_remote_state(
        self,
        final_directory: str,
    ) -> dict[str, str]:
        pattern = f"{final_directory}.uploading-*"
        command = "\n".join([
            f"if test -d {shlex.quote(final_directory)}; then",
            "  printf 'FINAL\\n'",
            "else",
            f"  for path in {pattern}; do",
            "    if test -d \"$path\"; then printf 'STAGING\\t%s\\n' \"$path\"; break; fi",
            "  done",
            "fi",
        ])
        output = self._run_ssh(command, "inspect remote upload state")
        for line in output.splitlines():
            if line == "FINAL":
                return {"kind": "final", "path": final_directory}
            if line.startswith("STAGING\t"):
                return {"kind": "staging", "path": line.split("\t", 1)[1]}
        return {"kind": "new", "path": ""}

    def _prepare_staging_directory(
        self,
        final_directory: str,
        staging_directory: str,
    ) -> None:
        batch_directory = str(PurePosixPath(final_directory).parent)
        command = " && ".join([
            "umask 077",
            f"mkdir -p {shlex.quote(batch_directory)}",
            f"test ! -e {shlex.quote(final_directory)}",
            f"mkdir {shlex.quote(staging_directory)}",
        ])
        self._run_ssh(command, "prepare remote staging directory")

    @staticmethod
    def _validate_expected_hashes(
        job: dict[str, Any],
        remote_hashes: dict[str, str],
    ) -> None:
        for file in job.get("files", []):
            name = str(file["name"])
            if remote_hashes.get(name) != str(file["sha256"]):
                raise RemoteUploadError(f"Remote SHA-256 mismatch: {name}")

    def _validate_local_files(
        self,
        job: dict[str, Any],
    ) -> None:
        files = job.get("files", [])

        if not isinstance(files, list):
            raise TypeError(
                "Planned files must be a list"
            )

        names = {
            str(item.get("name", ""))
            for item in files
        }

        if names != self.FILE_NAMES:
            raise ValueError(
                "Upload plan must contain exactly five files"
            )

        for item in files:
            name = str(item["name"])
            path = Path(
                str(item["local_path"])
            ).resolve()

            if not path.is_file():
                raise FileNotFoundError(
                    f"Local file is missing: {path}"
                )

            if path.name != name:
                raise ValueError(
                    f"Local file name changed: {path}"
                )

            actual_hash = self._sha256(path)

            if actual_hash != str(item["sha256"]):
                raise ValueError(
                    f"Local file changed after approval: {name}"
                )

            if path.stat().st_size != int(
                item["size_bytes"]
            ):
                raise ValueError(
                    f"Local file size changed: {name}"
                )

    def _validate_remote_directory(
        self,
        remote_directory: str,
    ) -> None:
        if not self.SAFE_REMOTE_PATH.fullmatch(
            remote_directory
        ):
            raise ValueError(
                "Unsafe remote directory"
            )

        root = PurePosixPath(
            self.settings.remote_runs_root
        )
        path = PurePosixPath(remote_directory)

        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(
                "Remote directory escaped configured root"
            ) from error

        if path == root:
            raise ValueError(
                "A job cannot overwrite the runs root"
            )

    def _remote_hashes(
        self,
        remote_directory: str,
        require_complete: bool = True,
    ) -> dict[str, str]:
        names = sorted(self.FILE_NAMES)

        checks = " ".join(shlex.quote(name) for name in names)
        command = (
            f"cd {shlex.quote(remote_directory)} && "
            f"for name in {checks}; do "
            "test ! -f \"$name\" || sha256sum -- \"$name\"; done"
        )

        output = self._run_ssh(
            command,
            "calculate remote SHA-256",
        )

        hashes: dict[str, str] = {}

        for line in output.splitlines():
            parts = line.strip().split(maxsplit=1)

            if len(parts) != 2:
                continue

            digest = parts[0].strip()
            name = parts[1].strip().lstrip("*")

            if re.fullmatch(
                r"[0-9a-fA-F]{64}",
                digest,
            ):
                hashes[name] = digest.lower()

        if require_complete and set(hashes) != self.FILE_NAMES:
            raise RemoteUploadError(
                "Remote hash output is incomplete"
            )

        return hashes

    def _upload_files(
        self,
        local_paths: list[Path],
        remote_directory: str,
    ) -> None:
        scp = shutil.which("scp")

        if not scp:
            raise RemoteUploadError(
                "Windows OpenSSH scp was not found"
            )

        target = (
            f"{self.settings.ssh.user}@"
            f"{self.settings.ssh.host}:"
            f"{remote_directory}/"
        )

        command = [
            scp,
            "-P",
            str(self.settings.ssh.port),
            "-i",
            str(
                self.settings.ssh.key_path.resolve()
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
            *(str(path) for path in local_paths),
            target,
        ]

        self._run_process(
            command,
            "upload job files: " + ", ".join(path.name for path in local_paths),
        )

    def _upload_file(self, local_path: Path, remote_directory: str) -> None:
        self._upload_files([local_path], remote_directory)

    def _run_ssh(
        self,
        remote_command: str,
        operation: str,
    ) -> str:
        ssh = shutil.which("ssh")

        if not ssh:
            raise RemoteUploadError(
                "Windows OpenSSH ssh was not found"
            )

        command = [
            ssh,
            "-T",
            "-p",
            str(self.settings.ssh.port),
            "-i",
            str(
                self.settings.ssh.key_path.resolve()
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

        return self._run_process(
            command,
            operation,
        )

    def _run_process(
        self,
        command: list[str],
        operation: str,
    ) -> str:
        last_message = ""
        for attempt in range(1, self.settings.retry_attempts + 1):
            try:
                completed = subprocess.run(
                    command, capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=self.settings.timeout_seconds,
                    check=False, shell=False,
                )
                if not completed.returncode:
                    return completed.stdout.strip()
                last_message = completed.stderr.strip()[:500]
                if not self._is_transient_error(last_message):
                    break
            except subprocess.TimeoutExpired:
                last_message = "operation timed out"
            if attempt < self.settings.retry_attempts:
                time.sleep(self.settings.retry_delay_seconds * attempt)
        raise RemoteUploadError(f"{operation} failed: {last_message}")

    @staticmethod
    def _is_transient_error(message: str) -> bool:
        text = message.lower()
        return any(term in text for term in (
            "timed out", "connection reset", "connection closed",
            "connection refused", "temporarily unavailable",
            "kex_exchange_identification",
        ))

    def _result(
        self,
        status: str,
        jobs: list[dict[str, Any]],
        approved_count: int,
        errors: list[dict[str, Any]],
        verified_jobs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        verified = verified_jobs or []

        return {
            "schema_version": "c11.4.2",
            "stage": "remote_upload",
            "status": status,
            "approved_count": approved_count,
            "uploaded_count": sum(
                bool(job.get("upload_performed"))
                for job in jobs
            ),
            "verified_count": len(verified),
            "failed_count": len(jobs) - len(verified),
            "jobs": jobs,
            "verified_jobs": verified,
            "errors": errors,
            "remote_write_performed": any(
                bool(job.get("remote_write_performed"))
                for job in jobs
            ),
            "upload_performed": any(
                bool(job.get("upload_performed"))
                for job in jobs
            ),
            "submission_performed": False,
            "next_stage": (
                "c11.4.3_remote_submission_review"
            ),
        }

    @staticmethod
    def _sha256(
        path: Path,
    ) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)

        return digest.hexdigest()
