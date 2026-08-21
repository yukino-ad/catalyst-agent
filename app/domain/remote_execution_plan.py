from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


class RemoteExecutionPlanService:
    """Plan remote DFT paths without remote access or writes."""

    FILE_NAMES = {
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "POTCAR",
        "vasp.slurm",
    }

    SAFE_IDENTIFIER = re.compile(
        r"^[A-Za-z0-9._-]+$"
    )

    SAFE_REMOTE_ROOT = re.compile(
        r"^/[A-Za-z0-9._/+:-]+$"
    )

    def __init__(
        self,
        remote_runs_root: str | None = None,
    ) -> None:
        self.remote_runs_root = (
            remote_runs_root
            or os.getenv(
                "CLUSTER_REMOTE_RUNS_ROOT",
                "",
            ).strip()
        ).rstrip("/")

    def plan(
        self,
        jobs: list[dict[str, Any]],
        task_id: str,
        job_source: str,
    ) -> dict[str, Any]:
        if not isinstance(jobs, list):
            raise TypeError("jobs must be a list")

        if not jobs:
            return {
                "schema_version": "c11.4.1",
                "stage": "remote_execution_plan",
                "status": "remote_execution_plan_skipped",
                "task_id": task_id,
                "job_source": job_source,
                "job_count": 0,
                "jobs": [],
                "remote_write_performed": False,
                "upload_performed": False,
                "submission_performed": False,
            }

        safe_task_id = self._safe_identifier(
            task_id,
            "task_id",
        )

        if not self.SAFE_REMOTE_ROOT.fullmatch(
            self.remote_runs_root
        ):
            raise ValueError(
                "CLUSTER_REMOTE_RUNS_ROOT must be "
                "an absolute safe Unix path"
            )

        batch_directory = (
            f"{self.remote_runs_root}/{safe_task_id}"
        )

        planned_jobs = [
            self._plan_job(
                job=job,
                batch_directory=batch_directory,
            )
            for job in jobs
        ]

        plan_digest = self._plan_digest(
            task_id=safe_task_id,
            job_source=job_source,
            batch_directory=batch_directory,
            jobs=planned_jobs,
        )

        return {
            "schema_version": "c11.4.1",
            "stage": "remote_execution_plan",
            "status": "remote_execution_plan_ready",
            "task_id": safe_task_id,
            "job_source": job_source,
            "remote_batch_directory": batch_directory,
            "plan_digest": plan_digest,
            "job_count": len(planned_jobs),
            "jobs": planned_jobs,
            "required_human_confirmation": True,
            "overwrite_allowed": False,
            "remote_write_performed": False,
            "upload_performed": False,
            "submission_performed": False,
            "next_stage": "remote_upload_review",
        }

    def _plan_job(
        self,
        job: dict[str, Any],
        batch_directory: str,
    ) -> dict[str, Any]:
        if not isinstance(job, dict):
            raise TypeError("Every job must be a dictionary")

        job_id = self._safe_identifier(
            str(job.get("job_id", "")).strip(),
            "job_id",
        )

        local_directory = Path(
            str(job.get("job_dir", ""))
        ).resolve()

        if not local_directory.is_dir():
            raise FileNotFoundError(
                f"Local job directory does not exist: "
                f"{local_directory}"
            )

        actual_files = {
            path.name
            for path in local_directory.iterdir()
            if path.is_file()
        }

        if actual_files != self.FILE_NAMES:
            raise ValueError(
                f"{job_id} does not contain exactly "
                f"{sorted(self.FILE_NAMES)}"
            )

        files = []

        for name in sorted(self.FILE_NAMES):
            path = local_directory / name

            files.append({
                "name": name,
                "local_path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": self._sha256(path),
            })

        return {
            **job,
            "job_id": job_id,
            "local_job_directory": str(
                local_directory
            ),
            "remote_job_directory": (
                f"{batch_directory}/{job_id}"
            ),
            "files": files,
            "file_count": len(files),
            "upload_approved": False,
            "upload_performed": False,
            "remote_hash_verified": False,
            "submission_approved": False,
            "submission_performed": False,
        }

    def _safe_identifier(
        self,
        value: str,
        field_name: str,
    ) -> str:
        if not value:
            raise ValueError(
                f"{field_name} is required"
            )

        if not self.SAFE_IDENTIFIER.fullmatch(value):
            raise ValueError(
                f"{field_name} contains unsafe characters"
            )

        return value

    @staticmethod
    def _plan_digest(
        task_id: str,
        job_source: str,
        batch_directory: str,
        jobs: list[dict[str, Any]],
    ) -> str:
        payload = {
            "task_id": task_id,
            "job_source": job_source,
            "remote_batch_directory": batch_directory,
            "jobs": [{
                "job_id": job["job_id"],
                "scientific_identity": job.get("scientific_identity"),
                "remote_job_directory": (
                    job["remote_job_directory"]
                ),
                "files": [{
                    "name": item["name"],
                    "size_bytes": item["size_bytes"],
                    "sha256": item["sha256"],
                } for item in job["files"]],
            } for job in jobs],
        }

        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _sha256(
        path: Path,
    ) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)

        return digest.hexdigest()
