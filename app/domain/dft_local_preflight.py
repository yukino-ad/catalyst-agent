from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from app.domain.dft_input_bundle import (
    VaspInputBundleService,
)


class DFTLocalPreflightService:
    """Validate reviewed VASP files before any cluster access."""

    FILE_NAMES = {
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "POTCAR",
        "vasp.slurm",
    }

    TEXT_FILES = {
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "vasp.slurm",
    }

    WINDOWS_PATH_PATTERN = re.compile(
        rb"[A-Za-z]:[\\/]"
    )

    def __init__(
        self,
        allowed_roots: list[str | Path] | None = None,
    ) -> None:
        roots = allowed_roots or [
            "data/dft_formation_inputs",
            "data/dft_inputs",
            "data/adsorption_dft_inputs",
        ]
        self.allowed_roots = [
            Path(root).resolve()
            for root in roots
        ]

    def inspect(
        self,
        jobs: list[dict[str, Any]],
        preview: dict[str, Any],
        job_source: str,
    ) -> dict[str, Any]:
        if not isinstance(jobs, list):
            raise TypeError("jobs must be a list")

        if not isinstance(preview, dict):
            raise TypeError("preview must be a dictionary")

        if not jobs:
            return {
                "schema_version": "c11.2",
                "stage": "dft_local_preflight",
                "status": "dft_local_preflight_skipped",
                "job_source": job_source,
                "job_count": 0,
                "passed_count": 0,
                "failed_count": 0,
                "jobs": [],
                "eligible_jobs": [],
                "submission_performed": False,
                "next_stage": "c11.3_cluster_readonly_preflight",
            }

        bundles = {
            str(bundle.get("bundle_id", "")): bundle
            for bundle in preview.get("bundles", [])
            if isinstance(bundle, dict)
        }

        results = []
        eligible_jobs = []

        for job in jobs:
            try:
                result = self._inspect_one(
                    job=job,
                    bundles=bundles,
                    job_source=job_source,
                )
            except Exception as error:
                result = {
                    **job,
                    "local_preflight_status": "failed",
                    "local_preflight_passed": False,
                    "checks": [],
                    "errors": [{
                        "error_type": type(error).__name__,
                        "message": str(error),
                    }],
                }

            results.append(result)

            if result["local_preflight_passed"]:
                eligible_jobs.append(result)

        passed_count = len(eligible_jobs)
        failed_count = len(results) - passed_count

        if passed_count == len(results):
            status = "dft_local_preflight_passed"
        elif passed_count:
            status = "dft_local_preflight_partial"
        else:
            status = "dft_local_preflight_failed"

        return {
            "schema_version": "c11.2",
            "stage": "dft_local_preflight",
            "status": status,
            "job_source": job_source,
            "job_count": len(results),
            "passed_count": passed_count,
            "failed_count": failed_count,
            "jobs": results,
            "eligible_jobs": eligible_jobs,
            "submission_performed": False,
            "next_stage": "c11.3_cluster_readonly_preflight",
        }

    def _inspect_one(
        self,
        job: dict[str, Any],
        bundles: dict[str, dict[str, Any]],
        job_source: str,
    ) -> dict[str, Any]:
        if not isinstance(job, dict):
            raise TypeError("Every job must be a dictionary")

        job_id = str(job.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("job_id is required")

        if job_id not in bundles:
            raise ValueError(
                f"Preview bundle not found for {job_id}"
            )

        bundle = bundles[job_id]
        job_dir = Path(
            str(job.get("job_dir", ""))
        ).resolve()

        checks: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        self._check(
            checks,
            errors,
            "job_directory_exists",
            job_dir.is_dir(),
            f"Job directory does not exist: {job_dir}",
        )

        self._check(
            checks,
            errors,
            "job_directory_allowed",
            self._inside_allowed_root(job_dir),
            (
                "Job directory is outside approved roots: "
                f"{job_dir}"
            ),
        )

        if not job_dir.is_dir():
            return self._job_result(
                job,
                job_source,
                checks,
                errors,
            )

        actual_files = {
            path.name
            for path in job_dir.iterdir()
            if path.is_file()
        }

        self._check(
            checks,
            errors,
            "exact_five_file_set",
            actual_files == self.FILE_NAMES,
            (
                f"Expected {sorted(self.FILE_NAMES)}, "
                f"found {sorted(actual_files)}"
            ),
        )

        files = {
            name: job_dir / name
            for name in self.FILE_NAMES
        }

        for name, path in files.items():
            self._check(
                checks,
                errors,
                f"{name}_exists",
                path.is_file(),
                f"{name} does not exist: {path}",
            )

            self._check(
                checks,
                errors,
                f"{name}_inside_job_directory",
                path.parent.resolve() == job_dir,
                f"{name} escaped the job directory",
            )

            self._check(
                checks,
                errors,
                f"{name}_nonempty",
                path.is_file() and path.stat().st_size > 0,
                f"{name} is missing or empty",
            )

        if errors:
            return self._job_result(
                job,
                job_source,
                checks,
                errors,
            )

        preview = bundle.get("preview", {})

        for name in self.TEXT_FILES:
            actual_bytes = files[name].read_bytes()

            if name == "vasp.slurm":
                slurm_preview = preview.get(
                    "vasp.slurm",
                    {},
                )
                if not isinstance(slurm_preview, dict):
                    raise TypeError(
                        "vasp.slurm preview must be a dictionary"
                    )
                expected_text = str(
                    slurm_preview.get("full_text", "")
                )
            else:
                expected_text = str(
                    preview.get(name, "")
                )

            expected_bytes = expected_text.encode("utf-8")

            self._check(
                checks,
                errors,
                f"{name}_matches_reviewed_preview",
                actual_bytes == expected_bytes,
                f"{name} changed after human review",
            )

            self._check(
                checks,
                errors,
                f"{name}_uses_lf",
                b"\r\n" not in actual_bytes,
                f"{name} contains CRLF line endings",
            )

        source_poscar = Path(
            str(bundle.get("source_poscar_path", ""))
        )

        self._check(
            checks,
            errors,
            "source_poscar_exists",
            source_poscar.is_file(),
            f"Source POSCAR does not exist: {source_poscar}",
        )

        if source_poscar.is_file():
            finalized_poscar = files["POSCAR"].read_text(
                encoding="utf-8",
            ).replace("\r\n", "\n")
            approved_source_poscar = source_poscar.read_text(
                encoding="utf-8",
            ).replace("\r\n", "\n")
            self._check(
                checks,
                errors,
                "poscar_matches_source",
                finalized_poscar == approved_source_poscar,
                "POSCAR differs from the approved source structure",
            )

        elements, counts = self._poscar_species(
            files["POSCAR"]
        )

        expected_elements = [
            str(value)
            for value in job.get("element_order", [])
        ]

        self._check(
            checks,
            errors,
            "poscar_element_order",
            elements == expected_elements,
            (
                f"POSCAR elements {elements} differ from "
                f"job order {expected_elements}"
            ),
        )

        self._check_structure_identity(
            checks=checks,
            errors=errors,
            job=job,
            job_source=job_source,
            elements=elements,
            counts=counts,
        )

        potcar_plan = preview.get("POTCAR", [])
        planned_elements = [
            str(item.get("element", ""))
            for item in potcar_plan
        ]
        planned_potentials = [
            str(item.get("potential", ""))
            for item in potcar_plan
        ]

        self._check(
            checks,
            errors,
            "potcar_element_order",
            planned_elements == elements,
            (
                f"POTCAR element order {planned_elements} "
                f"differs from POSCAR {elements}"
            ),
        )

        self._check(
            checks,
            errors,
            "potcar_potential_order",
            planned_potentials
            == list(job.get("potcar_order", [])),
            "POTCAR potential order differs from reviewed job",
        )

        expected_potcar_hash = self._combined_potcar_hash(
            potcar_plan
        )
        actual_potcar_hash = self._file_sha256(
            files["POTCAR"]
        )

        self._check(
            checks,
            errors,
            "potcar_content",
            actual_potcar_hash == expected_potcar_hash,
            "POTCAR content differs from reviewed sources",
        )

        recalculated_digest = (
            VaspInputBundleService._preview_digest(
                poscar_text=str(preview.get("POSCAR", "")),
                incar_text=str(preview.get("INCAR", "")),
                kpoints_text=str(preview.get("KPOINTS", "")),
                slurm_text=str(
                    preview.get(
                        "vasp.slurm",
                        {},
                    ).get("full_text", "")
                ),
                potcar_plan=potcar_plan,
            )
        )

        expected_digest = str(
            job.get("preview_digest", "")
        )

        self._check(
            checks,
            errors,
            "preview_digest",
            recalculated_digest == expected_digest,
            "Preview digest no longer matches the job",
        )

        slurm_bytes = files["vasp.slurm"].read_bytes()

        self._check(
            checks,
            errors,
            "slurm_has_no_windows_path",
            not self.WINDOWS_PATH_PATTERN.search(
                slurm_bytes
            ),
            "vasp.slurm contains a Windows absolute path",
        )

        return self._job_result(
            job,
            job_source,
            checks,
            errors,
        )

    def _inside_allowed_root(
        self,
        path: Path,
    ) -> bool:
        for root in self.allowed_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue

        return False

    @classmethod
    def _check_structure_identity(
        cls,
        checks: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        job: dict[str, Any],
        job_source: str,
        elements: list[str],
        counts: list[int],
    ) -> None:
        atom_count = sum(counts)

        if job_source == "c6d_bulk_formation":
            expected_count = 32
            count_message = "Bulk POSCAR atom count must be 32"
        elif job_source == "c10_slab":
            expected_count = 48
            count_message = "Clean slab POSCAR atom count must be 48"
        elif job_source == "c12_5_adsorption":
            identity = job.get("scientific_identity", {})
            if not isinstance(identity, dict):
                identity = {}

            expected_count = identity.get("atom_count")
            count_message = (
                "Adsorption POSCAR atom count must match "
                "scientific_identity.atom_count"
            )
            cls._check(
                checks,
                errors,
                "single_adsorbate_instance",
                identity.get("adsorbate_instance_count") == 1
                and job.get("adsorbate_instance_count") == 1,
                "C12.6 requires exactly one adsorbate instance",
            )
            cls._check(
                checks,
                errors,
                "coadsorption_disabled",
                identity.get("coadsorption") is False
                and job.get("coadsorption") is False,
                "C12.6 does not allow coadsorption",
            )

            expected_composition = identity.get("composition", {})
            actual_composition = dict(zip(elements, counts))
            cls._check(
                checks,
                errors,
                "poscar_composition_matches_identity",
                isinstance(expected_composition, dict)
                and actual_composition == expected_composition,
                (
                    f"POSCAR composition {actual_composition} differs "
                    f"from scientific identity {expected_composition}"
                ),
            )
        else:
            expected_count = None
            count_message = (
                "POSCAR atom count must be 32 for bulk or 48 for slab"
            )

        if job_source == "c12_5_adsorption":
            count_passed = (
                isinstance(expected_count, int)
                and expected_count > 0
                and atom_count == expected_count
            )
        elif expected_count is not None:
            count_passed = atom_count == expected_count
        else:
            count_passed = atom_count in {32, 48}

        cls._check(
            checks,
            errors,
            "poscar_atom_count",
            count_passed,
            count_message,
        )

    @staticmethod
    def _poscar_species(
        path: Path,
    ) -> tuple[list[str], list[int]]:
        lines = path.read_text(
            encoding="utf-8",
        ).splitlines()

        if len(lines) < 8:
            raise ValueError("POSCAR is incomplete")

        elements = lines[5].split()

        try:
            counts = [
                int(value)
                for value in lines[6].split()
            ]
        except ValueError as error:
            raise ValueError(
                "POSCAR atom counts are invalid"
            ) from error

        if len(elements) != len(counts):
            raise ValueError(
                "POSCAR element/count columns differ"
            )

        return elements, counts

    @staticmethod
    def _combined_potcar_hash(
        plan: list[dict[str, Any]],
    ) -> str:
        digest = hashlib.sha256()

        for item in plan:
            source = Path(
                str(item.get("source_path", ""))
            )

            if not source.is_file():
                raise FileNotFoundError(
                    f"POTCAR source does not exist: {source}"
                )

            expected_hash = str(
                item.get("sha256", "")
            )

            actual_source_hash = (
                DFTLocalPreflightService
                ._file_sha256(source)
            )

            if actual_source_hash != expected_hash:
                raise ValueError(
                    f"POTCAR source changed: {source}"
                )

            with source.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def _check(
        checks: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        name: str,
        passed: bool,
        message: str,
    ) -> None:
        checks.append({
            "name": name,
            "passed": bool(passed),
        })

        if not passed:
            errors.append({
                "check": name,
                "message": message,
            })

    @staticmethod
    def _job_result(
        job: dict[str, Any],
        job_source: str,
        checks: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        passed = not errors

        return {
            **job,
            "job_source": job_source,
            "local_preflight_status": (
                "passed" if passed else "failed"
            ),
            "local_preflight_passed": passed,
            "checks": checks,
            "errors": errors,
            "submission_performed": False,
        }
