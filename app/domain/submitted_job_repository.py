from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SubmittedJobRepository:
    """Persist submitted Slurm jobs for later monitoring."""

    SAFE_IDENTIFIER = re.compile(
        r"^[A-Za-z0-9._-]+$"
    )
    SLURM_JOB_ID = re.compile(r"^[0-9]+$")

    IDENTITY_FIELDS = (
        "slurm_job_id",
        "task_id",
        "job_id",
        "job_source",
        "remote_job_directory",
        "plan_digest",
        "scientific_identity",
    )

    def __init__(
        self,
        root: str | Path = "data/cluster_jobs",
    ) -> None:
        self.root = Path(root)
        self.records_directory = (
            self.root / "records"
        )
        self.latest_path = (
            self.root / "latest_submission.json"
        )

    def record_submission(
        self,
        task_id: str,
        job_source: str,
        plan_digest: str,
        jobs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist all successfully submitted jobs."""

        if not isinstance(jobs, list):
            raise TypeError(
                "jobs must be a list"
            )

        if not jobs:
            return {
                "schema_version": "c11.5.1",
                "stage": "submission_recording",
                "status": (
                    "submission_recording_skipped"
                ),
                "recorded_count": 0,
                "existing_count": 0,
                "failed_count": 0,
                "records": [],
                "errors": [],
                "latest_manifest_path": None,
                "next_stage": (
                    "c11.5.2_job_monitoring"
                ),
            }

        safe_task_id = self._safe_identifier(
            task_id,
            "task_id",
        )

        if not isinstance(job_source, str):
            raise TypeError(
                "job_source must be a string"
            )

        if not isinstance(plan_digest, str):
            raise TypeError(
                "plan_digest must be a string"
            )

        if not plan_digest.strip():
            raise ValueError(
                "plan_digest is required"
            )

        recorded: list[dict[str, Any]] = []
        existing_count = 0
        errors: list[dict[str, Any]] = []

        for job in jobs:
            try:
                record = self._build_record(
                    task_id=safe_task_id,
                    job_source=job_source.strip(),
                    plan_digest=plan_digest.strip(),
                    job=job,
                )

                saved, already_existed = (
                    self._write_record(record)
                )

                recorded.append(saved)

                if already_existed:
                    existing_count += 1

            except Exception as error:
                errors.append({
                    "job_id": (
                        job.get("job_id")
                        if isinstance(job, dict)
                        else None
                    ),
                    "slurm_job_id": (
                        job.get("slurm_job_id")
                        if isinstance(job, dict)
                        else None
                    ),
                    "error_type": (
                        type(error).__name__
                    ),
                    "message": str(error),
                })

        new_count = (
            len(recorded) - existing_count
        )

        if recorded and not errors:
            status = "submission_jobs_recorded"
        elif recorded:
            status = (
                "submission_recording_partial"
            )
        else:
            status = "submission_recording_failed"

        result = {
            "schema_version": "c11.5.1",
            "stage": "submission_recording",
            "status": status,
            "task_id": safe_task_id,
            "job_source": job_source.strip(),
            "plan_digest": plan_digest.strip(),
            "submitted_input_count": len(jobs),
            "recorded_count": len(recorded),
            "new_record_count": new_count,
            "existing_count": existing_count,
            "failed_count": len(errors),
            "records": recorded,
            "errors": errors,
            "latest_manifest_path": str(
                self.latest_path.resolve()
            ),
            "next_stage": (
                "c11.5.2_job_monitoring"
            ),
        }

        if recorded:
            self._atomic_write_json(
                self.latest_path,
                result,
            )

        return result

    def get(
        self,
        slurm_job_id: str,
    ) -> dict[str, Any] | None:
        """Return one persisted job by Slurm ID."""

        safe_id = self._safe_slurm_job_id(
            slurm_job_id
        )
        path = (
            self.records_directory
            / f"{safe_id}.json"
        )

        if not path.is_file():
            return None

        return self._read_json(path)

    def list_records(
        self,
    ) -> list[dict[str, Any]]:
        """Return all persisted jobs."""

        if not self.records_directory.is_dir():
            return []

        records = []

        for path in sorted(
            self.records_directory.glob("*.json")
        ):
            records.append(
                self._read_json(path)
            )

        return records

    def update(
        self,
        slurm_job_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically update mutable monitoring fields."""

        if not isinstance(changes, dict):
            raise TypeError("changes must be a dictionary")

        immutable = set(self.IDENTITY_FIELDS) | {
            "schema_version",
            "submitted_at",
            "recorded_at",
        }
        forbidden = immutable & set(changes)
        if forbidden:
            raise ValueError(
                "Immutable job fields cannot be changed: "
                + ", ".join(sorted(forbidden))
            )

        current = self.get(slurm_job_id)
        if current is None:
            raise FileNotFoundError(
                f"Unknown Slurm job ID: {slurm_job_id}"
            )

        updated = {**current, **changes}
        path = (
            self.records_directory
            / f"{self._safe_slurm_job_id(slurm_job_id)}.json"
        )
        self._atomic_write_json(path, updated)
        return updated

    def _build_record(
        self,
        task_id: str,
        job_source: str,
        plan_digest: str,
        job: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(job, dict):
            raise TypeError(
                "Every submitted job must be "
                "a dictionary"
            )

        if (
            job.get("submission_status")
            != "submitted"
        ):
            raise ValueError(
                "Only submitted jobs may be recorded"
            )

        if not job.get(
            "submission_performed",
            False,
        ):
            raise ValueError(
                "submission_performed must be true"
            )

        slurm_job_id = (
            self._safe_slurm_job_id(
                str(job.get("slurm_job_id", ""))
            )
        )

        job_id = self._safe_identifier(
            str(job.get("job_id", "")),
            "job_id",
        )

        remote_directory = str(
            job.get(
                "remote_job_directory",
                "",
            )
        ).strip()

        if not remote_directory.startswith("/"):
            raise ValueError(
                "remote_job_directory must be "
                "an absolute Unix path"
            )

        submitted_at = str(
            job.get("submitted_at", "")
        ).strip()

        if not submitted_at:
            raise ValueError(
                "submitted_at is required"
            )

        now = (
            datetime.now(timezone.utc)
            .isoformat()
        )

        scientific_identity = self._validate_scientific_identity(
            job.get("scientific_identity"), job_source
        )

        return {
            "schema_version": "c11.5.1",
            "slurm_job_id": slurm_job_id,
            "task_id": task_id,
            "job_id": job_id,
            "job_source": job_source,
            "remote_job_directory": (
                remote_directory
            ),
            "plan_digest": plan_digest,
            "scientific_identity": scientific_identity,
            "submitted_at": submitted_at,
            "recorded_at": now,
            "monitoring_status": (
                "awaiting_first_poll"
            ),
            "scheduler_state": "UNKNOWN",
            "terminal": False,
            "last_polled_at": None,
            "last_scheduler_message": None,
            "automatic_retry_allowed": False,
        }

    @staticmethod
    def _validate_scientific_identity(
        value: Any,
        job_source: str,
    ) -> dict[str, Any] | None:
        if value is None:
            if job_source in {
                "c6d_bulk_formation",
                "c10_slab",
                "c12_5_adsorption",
            }:
                raise ValueError(
                    f"{job_source} requires scientific_identity"
                )
            return None

        if not isinstance(value, dict):
            raise ValueError(
                "scientific_identity must be a dictionary"
            )

        if job_source == "c6d_bulk_formation":
            return (
                SubmittedJobRepository
                ._validate_bulk_identity(value)
            )

        if job_source == "c10_slab":
            return (
                SubmittedJobRepository
                ._validate_clean_slab_identity(value)
            )

        if job_source == "c12_5_adsorption":
            return (
                SubmittedJobRepository
                ._validate_adsorption_identity(value)
            )

        return json.loads(json.dumps(value))

    @staticmethod
    def _validate_bulk_identity(
        value: dict[str, Any],
    ) -> dict[str, Any]:
        required = {
            "structure_id", "candidate_id", "calculation_type", "composition",
            "element_order", "atom_count", "energy_field",
            "reference_data_version", "source_poscar_sha256",
            "source_poscar_path", "vasp_config_version",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(
                "scientific_identity is missing: " + ", ".join(missing)
            )
        if value["calculation_type"] != "bulk_formation_relax":
            raise ValueError("Unsupported C6D calculation_type")
        composition = value["composition"]
        if not isinstance(composition, dict) or not composition:
            raise ValueError("scientific_identity composition is invalid")
        if sum(composition.values()) != value["atom_count"]:
            raise ValueError("scientific_identity atom_count is inconsistent")
        return json.loads(json.dumps(value))

    @staticmethod
    def _validate_clean_slab_identity(
        value: dict[str, Any],
    ) -> dict[str, Any]:
        required = {
            "calculation_type",
            "slab_id",
            "candidate_id",
            "atom_count",
            "element_order",
            "composition",
            "energy_field",
            "source_poscar_path",
            "vasp_config_version",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(
                "Clean slab identity is missing: "
                + ", ".join(missing)
            )

        if value["calculation_type"] != "clean_slab_relax":
            raise ValueError(
                "Unsupported clean slab calculation_type"
            )

        composition = value["composition"]
        if (
            not isinstance(composition, dict)
            or not composition
            or any(
                not isinstance(count, int) or count <= 0
                for count in composition.values()
            )
            or sum(composition.values()) != value["atom_count"]
        ):
            raise ValueError(
                "Clean slab composition and atom_count "
                "are inconsistent"
            )

        return json.loads(json.dumps(value))

    @staticmethod
    def _validate_adsorption_identity(
        value: dict[str, Any],
    ) -> dict[str, Any]:
        required = {
            "calculation_type",
            "adsorption_structure_id",
            "candidate_id",
            "source_clean_slab_id",
            "site_id",
            "site_type",
            "adsorbate",
            "adsorbate_instance_count",
            "coadsorption",
            "atom_count",
            "element_order",
            "composition",
            "energy_field",
            "source_poscar_path",
            "source_poscar_sha256",
            "vasp_config_version",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(
                "Adsorption scientific_identity is missing: "
                + ", ".join(missing)
            )

        if value["calculation_type"] != "adsorption_relax":
            raise ValueError(
                "Unsupported adsorption calculation_type"
            )

        if value["adsorbate_instance_count"] != 1:
            raise ValueError(
                "Adsorption task must contain one adsorbate instance"
            )

        if value["coadsorption"] is not False:
            raise ValueError("Coadsorption is not allowed")

        for field in (
            "adsorption_structure_id",
            "candidate_id",
            "source_clean_slab_id",
            "site_id",
            "site_type",
            "adsorbate",
            "source_poscar_path",
            "vasp_config_version",
        ):
            if not str(value[field]).strip():
                raise ValueError(
                    f"Adsorption {field} must not be empty"
                )

        if not re.fullmatch(
            r"[0-9a-fA-F]{64}",
            str(value["source_poscar_sha256"]),
        ):
            raise ValueError(
                "Adsorption source_poscar_sha256 is invalid"
            )

        composition = value["composition"]
        if (
            not isinstance(composition, dict)
            or not composition
            or any(
                not isinstance(count, int) or count <= 0
                for count in composition.values()
            )
            or sum(composition.values()) != value["atom_count"]
        ):
            raise ValueError(
                "Adsorption composition and atom_count are inconsistent"
            )

        if (
            not isinstance(value["element_order"], list)
            or set(value["element_order"]) != set(composition)
        ):
            raise ValueError(
                "Adsorption element_order is inconsistent"
            )

        return json.loads(json.dumps(value))

    def _write_record(
        self,
        record: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        slurm_job_id = record[
            "slurm_job_id"
        ]

        path = (
            self.records_directory
            / f"{slurm_job_id}.json"
        )

        if path.exists():
            existing = self._read_json(path)
            self._validate_same_identity(
                existing=existing,
                incoming=record,
            )
            return existing, True

        self._atomic_write_json(
            path,
            record,
        )

        return {
            **record,
            "record_path": str(
                path.resolve()
            ),
        }, False

    def _validate_same_identity(
        self,
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> None:
        for field in self.IDENTITY_FIELDS:
            if (
                existing.get(field)
                != incoming.get(field)
            ):
                raise ValueError(
                    "Existing Slurm job record "
                    f"conflicts on field: {field}"
                )

    def _atomic_write_json(
        self,
        path: Path,
        value: dict[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = path.with_name(
            f".{path.name}.tmp-"
            f"{uuid.uuid4().hex}"
        )

        try:
            temporary.write_text(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

            temporary.replace(path)

        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _read_json(
        path: Path,
    ) -> dict[str, Any]:
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(value, dict):
            raise TypeError(
                f"Job record is not an object: "
                f"{path}"
            )

        return value

    def _safe_identifier(
        self,
        value: str,
        field_name: str,
    ) -> str:
        text = value.strip()

        if not text:
            raise ValueError(
                f"{field_name} is required"
            )

        if not self.SAFE_IDENTIFIER.fullmatch(
            text
        ):
            raise ValueError(
                f"{field_name} contains unsafe "
                "characters"
            )

        return text

    def _safe_slurm_job_id(
        self,
        value: str,
    ) -> str:
        text = value.strip()

        if not self.SLURM_JOB_ID.fullmatch(
            text
        ):
            raise ValueError(
                "slurm_job_id must contain "
                "digits only"
            )

        return text
