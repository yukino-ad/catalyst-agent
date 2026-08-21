from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Any

from app.domain.cluster_transport import ClusterTransport
from app.domain.remote_upload import RemoteUploadSettings
from app.domain.submitted_job_repository import SubmittedJobRepository


class ResultDownloadService:
    FILES = (
        "OUTCAR", "OSZICAR", "CONTCAR", "vasprun.xml",
        "slurm.out", "slurm.err", "XDATCAR",
    )

    def __init__(
        self,
        repository: SubmittedJobRepository | None = None,
        transport: ClusterTransport | None = None,
        output_root: str | Path = "data/cluster_results",
        remote_runs_root: str | None = None,
    ) -> None:
        self.repository = repository or SubmittedJobRepository()
        self.transport = transport or ClusterTransport()
        self.output_root = Path(output_root)
        self.remote_runs_root = remote_runs_root or RemoteUploadSettings.from_environment().remote_runs_root

    def download(self, review: dict[str, Any]) -> dict[str, Any]:
        self._validate_review(review)
        downloaded, errors = [], []
        for job_id in review["approved_slurm_job_ids"]:
            record = self.repository.get(job_id)
            try:
                if not record or not record.get("download_eligible"):
                    raise ValueError("Job is not eligible for result download")
                downloaded.append(self._download_one(record))
            except Exception as error:
                errors.append({
                    "slurm_job_id": job_id,
                    "error_type": type(error).__name__,
                    "message": str(error),
                })
        return {
            "schema_version": "c11.5.4",
            "stage": "result_download",
            "status": "result_download_completed" if downloaded and not errors else (
                "result_download_partial" if downloaded else "result_download_failed"
            ),
            "downloaded_count": len(downloaded),
            "failed_count": len(errors),
            "jobs": downloaded,
            "errors": errors,
            "next_stage": "c11.5.5_vasp_result_parsing",
        }

    def _download_one(self, record: dict[str, Any]) -> dict[str, Any]:
        remote = self.transport.validate_remote_child(
            record["remote_job_directory"], self.remote_runs_root
        )
        local = self.output_root / record["task_id"] / record["slurm_job_id"]
        local.mkdir(parents=True, exist_ok=True)
        approved_names = (*self.FILES, f"slurm-{record['slurm_job_id']}.out")
        available = set(self.transport.run(
            f"cd {self.transport.quote(remote)} && for f in {' '.join(approved_names)}; do test -f \"$f\" && printf '%s\\n' \"$f\"; done"
        ).splitlines())
        files = []
        for name in approved_names:
            if name not in available:
                continue
            remote_file = str(PurePosixPath(remote) / name)
            local_file = local / name
            self.transport.download(remote_file, local_file)
            files.append({
                "name": name,
                "path": str(local_file.resolve()),
                "size_bytes": local_file.stat().st_size,
                "sha256": self._sha256(local_file),
            })
        if not files:
            raise FileNotFoundError("No approved output files exist remotely")
        manifest = {
            "local_result_directory": str(local.resolve()),
            "downloaded_files": files,
            "download_status": "downloaded",
        }
        self.repository.update(record["slurm_job_id"], manifest)
        return {**record, **manifest}

    @staticmethod
    def _validate_review(review: dict[str, Any]) -> None:
        if not isinstance(review, dict) or review.get("status") != "result_download_approved":
            raise ValueError("Result download is not approved")
        ids = review.get("approved_slurm_job_ids", [])
        if not isinstance(ids, list) or not ids or any(not str(value).isdigit() for value in ids):
            raise ValueError("Approved Slurm job IDs are invalid")
        expected = "DOWNLOAD " + ",".join(ids)
        if review.get("confirmation_text") != expected:
            raise ValueError("Download confirmation text does not match")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
