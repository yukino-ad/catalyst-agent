from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any


class VaspInputBundleService:
    """Preview and finalize five-file VASP calculation bundles."""

    MAX_SLABS = 3
    FILE_NAMES = (
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "POTCAR",
        "vasp.slurm",
    )

    def __init__(
        self,
        output_root: str | Path = "data/dft_inputs",
        config_path: str | Path = (
            "configs/dft/vasp_slab_v1.json"
        ),
        pbe_root: str | Path = "database/PBE",
    ) -> None:
        self.output_root = Path(output_root)
        self.config_path = Path(config_path)
        self.pbe_root = Path(pbe_root)

    def preview(
        self,
        approved_slabs: list[dict[str, Any]],
        task_id: str,
    ) -> dict[str, Any]:
        if not isinstance(approved_slabs, list):
            raise TypeError("approved_slabs must be a list")

        if len(approved_slabs) > self.MAX_SLABS:
            raise ValueError("C10 can process at most 3 slabs")

        if not approved_slabs:
            return {
                "schema_version": "c10.0",
                "stage": "c10_preview",
                "status": "dft_input_preview_skipped",
                "bundle_count": 0,
                "bundles": [],
            }

        clean_task_id = self._safe_id(task_id)
        config = self._load_config()

        bundles = [
            self._preview_one(
                slab=slab,
                task_id=clean_task_id,
                config=config,
            )
            for slab in approved_slabs
        ]

        return {
            "schema_version": "c10.0",
            "stage": "c10_preview",
            "status": "dft_input_preview_completed",
            "task_id": clean_task_id,
            "bundle_count": len(bundles),
            "bundles": bundles,
            "formal_files_written": False,
            "requires_human_confirmation": True,
            "next_stage": "c10_review",
        }

    def finalize(
        self,
        preview: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(preview, dict):
            raise TypeError("preview must be a dictionary")
        if not isinstance(review, dict):
            raise TypeError("review must be a dictionary")

        bundles = preview.get("bundles", [])
        approved_ids = self._string_list(
            review.get("approve", [])
        )
        confirmations = review.get(
            "file_confirmations",
            {},
        )

        if not isinstance(confirmations, dict):
            raise TypeError(
                "file_confirmations must be a dictionary"
            )

        known = {
            bundle["bundle_id"]: bundle
            for bundle in bundles
        }

        unknown = sorted(set(approved_ids) - set(known))
        if unknown:
            raise ValueError(
                "Unknown bundle IDs: " + ", ".join(unknown)
            )

        jobs: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        for bundle_id in approved_ids:
            bundle = known[bundle_id]

            try:
                self._validate_confirmations(
                    bundle_id=bundle_id,
                    confirmations=confirmations,
                )
                jobs.append(
                    self._finalize_one(bundle)
                )
            except Exception as error:
                failures.append({
                    "bundle_id": bundle_id,
                    "error_type": type(error).__name__,
                    "message": str(error),
                })

        if jobs and not failures:
            status = "dft_input_preparation_completed"
        elif jobs:
            status = "dft_input_preparation_partial"
        elif approved_ids:
            status = "dft_input_preparation_failed"
        else:
            status = "dft_input_preparation_skipped"

        return {
            "schema_version": "c10.0",
            "stage": "c10_finalize",
            "status": status,
            "approved_bundle_count": len(approved_ids),
            "prepared_job_count": len(jobs),
            "failure_count": len(failures),
            "jobs": jobs,
            "failures": failures,
            "submission_performed": False,
            "next_stage": "c11_cluster_preflight",
        }

    def _preview_one(
        self,
        slab: dict[str, Any],
        task_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_approved_slab(slab)

        slab_id = str(slab["slab_id"]).strip()
        bundle_id = self._safe_id(slab_id)
        source = Path(
            str(slab["poscar_path"])
        ).resolve()

        poscar_text = source.read_text(encoding="utf-8")
        elements, counts = self._poscar_species(
            poscar_text
        )

        if len(elements) != 5:
            raise ValueError(
                "C10 expects exactly five elements"
            )
        if sum(counts) != 48:
            raise ValueError(
                "C10 expects exactly 48 atoms"
            )

        incar_text = self._build_incar(
            system_name="-".join(elements),
            elements=elements,
            counts=counts,
            config=config,
        )
        kpoints_text = (
            "\n".join(config["kpoints"]) + "\n"
        )
        slurm_text = self._build_slurm(
            job_name=bundle_id,
            config=config,
        )
        potcar_plan = self._potcar_plan(
            elements=elements,
            config=config,
        )

        preview_digest = self._preview_digest(
            poscar_text=poscar_text,
            incar_text=incar_text,
            kpoints_text=kpoints_text,
            slurm_text=slurm_text,
            potcar_plan=potcar_plan,
        )

        return {
            "schema_version": "c10.0",
            "bundle_id": bundle_id,
            "task_id": task_id,
            "slab_id": slab_id,
            "candidate_id": slab.get("candidate_id"),
            "source_poscar_path": str(source),
            "elements": elements,
            "counts": counts,
            "atom_count": sum(counts),
            "preview": {
                "POSCAR": poscar_text,
                "INCAR": incar_text,
                "KPOINTS": kpoints_text,
                "POTCAR": potcar_plan,
                "vasp.slurm": {
                    "job_name": bundle_id,
                    "nodes": config["slurm"]["nodes"],
                    "tasks_per_node": (
                        config["slurm"]["tasks_per_node"]
                    ),
                    "partition": (
                        config["slurm"]["partition"]
                    ),
                    "module_name": (
                        config["slurm"]["module_name"]
                    ),
                    "command": config["slurm"]["command"],
                    "full_text": slurm_text,
                },
            },
            "preview_digest": preview_digest,
            "preview_version": 1,
            "formal_files_written": False,
            "requires_human_confirmation": True,
        }

    def _finalize_one(
        self,
        bundle: dict[str, Any],
    ) -> dict[str, Any]:
        preview = bundle["preview"]

        recalculated_digest = self._preview_digest(
            poscar_text=preview["POSCAR"],
            incar_text=preview["INCAR"],
            kpoints_text=preview["KPOINTS"],
            slurm_text=preview["vasp.slurm"]["full_text"],
            potcar_plan=preview["POTCAR"],
        )

        if recalculated_digest != bundle["preview_digest"]:
            raise ValueError(
                "Preview content changed after human review"
            )

        task_dir = (
            self.output_root
            / self._safe_id(bundle["task_id"])
        )
        final_dir = task_dir / bundle["bundle_id"]

        if final_dir.exists():
            raise FileExistsError(
                f"Formal DFT directory already exists: "
                f"{final_dir}"
            )

        task_dir.mkdir(parents=True, exist_ok=True)

        temporary_dir = (
            task_dir
            / (
                f".{bundle['bundle_id']}.tmp-"
                f"{uuid.uuid4().hex[:8]}"
            )
        )
        temporary_dir.mkdir()

        try:
            self._write_text(
                temporary_dir / "POSCAR",
                preview["POSCAR"],
            )
            self._write_text(
                temporary_dir / "INCAR",
                preview["INCAR"],
            )
            self._write_text(
                temporary_dir / "KPOINTS",
                preview["KPOINTS"],
            )
            self._write_potcar(
                output_path=temporary_dir / "POTCAR",
                plan=preview["POTCAR"],
            )
            self._write_text(
                temporary_dir / "vasp.slurm",
                preview["vasp.slurm"]["full_text"],
            )

            actual_files = sorted(
                path.name
                for path in temporary_dir.iterdir()
                if path.is_file()
            )
            expected_files = sorted(self.FILE_NAMES)

            if actual_files != expected_files:
                raise RuntimeError(
                    "Generated VASP file set is incomplete"
                )

            temporary_dir.rename(final_dir)

        except Exception:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir)
            raise

        return {
            "schema_version": "c10.0",
            "job_id": bundle["bundle_id"],
            "slab_id": bundle["slab_id"],
            "candidate_id": bundle.get(
                "candidate_id"
            ),
            "job_dir": str(final_dir.resolve()),
            "files": {
                name: str(
                    (final_dir / name).resolve()
                )
                for name in self.FILE_NAMES
            },
            "element_order": bundle["elements"],
            "potcar_order": [
                item["potential"]
                for item in preview["POTCAR"]
            ],
            "preview_digest": bundle[
                "preview_digest"
            ],
            "scientific_identity": {
                "calculation_type": "clean_slab_relax",
                "slab_id": bundle["slab_id"],
                "candidate_id": bundle.get(
                    "candidate_id",
                    "",
                ),
                "atom_count": bundle["atom_count"],
                "element_order": list(
                    bundle["elements"]
                ),
                "composition": dict(zip(
                    bundle["elements"],
                    bundle["counts"],
                )),
                "energy_field": "final_toten_ev",
                "source_poscar_path": str(
                    Path(
                        bundle["source_poscar_path"]
                    ).resolve()
                ),
                "vasp_config_version": "vasp-slab-v1",
            },
            "file_count": 5,
            "submission_ready": True,
            "submitted": False,
            "status": "dft_input_files_created",
        }

    def _potcar_plan(
        self,
        elements: list[str],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        mapping = config["potcar_mapping"]
        plan = []

        for element in elements:
            if element not in mapping:
                raise KeyError(
                    f"No POTCAR mapping for {element}"
                )

            potential = mapping[element]
            path = (
                self.pbe_root
                / potential
                / "POTCAR"
            ).resolve()

            if not path.is_file():
                raise FileNotFoundError(
                    f"POTCAR does not exist: {path}"
                )

            plan.append({
                "element": element,
                "potential": potential,
                "source_path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": self._file_sha256(path),
                "exists": True,
            })

        return plan

    @staticmethod
    def _build_incar(
        system_name: str,
        elements: list[str],
        counts: list[int],
        config: dict[str, Any],
    ) -> str:
        incar = config["incar"]

        lines = [f"SYSTEM = {system_name}", ""]

        for key, value in incar.items():
            lines.append(f"{key:<8}= {value}")

        magnetic = set(
            config["magnetic_elements"]
        )

        if any(
            element in magnetic
            for element in elements
        ):
            magmom = [
                (
                    f"{count}*2.0"
                    if element in magnetic
                    else f"{count}*0.0"
                )
                for element, count
                in zip(elements, counts)
            ]
            lines.extend([
                "",
                "ISPIN   = 2",
                f"MAGMOM  = {' '.join(magmom)}",
            ])
        else:
            lines.extend([
                "",
                "ISPIN   = 1",
            ])

        return "\n".join(lines) + "\n"

    @staticmethod
    def _build_slurm(
        job_name: str,
        config: dict[str, Any],
    ) -> str:
        slurm = config["slurm"]

        return (
            "#!/bin/bash\n"
            f"#SBATCH -J {job_name}\n"
            f"#SBATCH -N {slurm['nodes']}\n"
            "#SBATCH --ntasks-per-node="
            f"{slurm['tasks_per_node']}\n"
            f"#SBATCH -p {slurm['partition']}\n"
            "\n"
            "module purge\n"
            f"module load {slurm['module_name']}\n"
            "\n"
            "export MKL_DEBUG_CPU_TYPE=5\n"
            "export MKL_CBWR=AVX2\n"
            "export I_MPI_PIN_DOMAIN=numa\n"
            "\n"
            f"{slurm['command']}\n"
        )

    @staticmethod
    def _poscar_species(
        text: str,
    ) -> tuple[list[str], list[int]]:
        lines = text.splitlines()

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
                "C10 requires a VASP 5 POSCAR"
            ) from error

        if len(elements) != len(counts):
            raise ValueError(
                "POSCAR element/count columns differ"
            )

        coordinate_line = lines[7].strip().lower()
        if coordinate_line.startswith("selective"):
            if len(lines) < 9:
                raise ValueError("POSCAR is incomplete")
            coordinate_line = lines[8].strip().lower()

        if not coordinate_line.startswith(("direct", "cartesian")):
            raise ValueError(
                "POSCAR lacks Direct or Cartesian coordinates"
            )

        return elements, counts

    @staticmethod
    def _validate_approved_slab(
        slab: dict[str, Any],
    ) -> None:
        if not isinstance(slab, dict):
            raise TypeError(
                "Every slab must be a dictionary"
            )
        if not str(
            slab.get("slab_id", "")
        ).strip():
            raise ValueError("slab_id is required")
        if (
            slab.get("slab_review_status")
            != "approved_for_dft"
        ):
            raise ValueError(
                "C10 only accepts C9-approved slabs"
            )
        if not slab.get(
            "eligible_for_dft_review",
            False,
        ):
            raise ValueError(
                "Slab failed C9 quality inspection"
            )
        source = Path(
            str(slab.get("poscar_path", ""))
        )
        if not source.is_file():
            raise FileNotFoundError(
                f"Slab POSCAR does not exist: "
                f"{source}"
            )

    @staticmethod
    def _validate_confirmations(
        bundle_id: str,
        confirmations: dict[str, Any],
    ) -> None:
        values = confirmations.get(
            bundle_id,
            {},
        )

        if not isinstance(values, dict):
            raise TypeError(
                f"Confirmation for {bundle_id} "
                "must be a dictionary"
            )

        missing = [
            name
            for name in VaspInputBundleService.FILE_NAMES
            if values.get(name) is not True
        ]

        if missing:
            raise ValueError(
                "All five files must be confirmed: "
                + ", ".join(missing)
            )

    @staticmethod
    def _preview_digest(
        poscar_text: str,
        incar_text: str,
        kpoints_text: str,
        slurm_text: str,
        potcar_plan: list[dict[str, Any]],
    ) -> str:
        potcar_fingerprint = [
            {
                "element": item["element"],
                "potential": item["potential"],
                "sha256": item["sha256"],
            }
            for item in potcar_plan
        ]

        payload = json.dumps(
            {
                "POSCAR": poscar_text,
                "INCAR": incar_text,
                "KPOINTS": kpoints_text,
                "POTCAR": potcar_fingerprint,
                "vasp.slurm": slurm_text,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _write_potcar(
        output_path: Path,
        plan: list[dict[str, Any]],
    ) -> None:
        with output_path.open("wb") as output:
            for item in plan:
                source = Path(
                    item["source_path"]
                )

                if (
                    VaspInputBundleService
                    ._file_sha256(source)
                    != item["sha256"]
                ):
                    raise ValueError(
                        f"POTCAR changed after preview: "
                        f"{source}"
                    )

                with source.open("rb") as handle:
                    shutil.copyfileobj(
                        handle,
                        output,
                    )

    def _load_config(
        self,
    ) -> dict[str, Any]:
        if not self.config_path.is_file():
            raise FileNotFoundError(
                f"Config does not exist: "
                f"{self.config_path}"
            )

        value = json.loads(
            self.config_path.read_text(
                encoding="utf-8"
            )
        )

        required = {
            "incar",
            "kpoints",
            "magnetic_elements",
            "potcar_mapping",
            "slurm",
        }

        missing = required - set(value)
        if missing:
            raise ValueError(
                "VASP config is missing: "
                + ", ".join(sorted(missing))
            )

        slurm = value["slurm"]
        if not isinstance(slurm, dict):
            raise TypeError(
                "VASP slurm config must be a dictionary"
            )

        required_slurm = {
            "nodes",
            "tasks_per_node",
            "partition",
            "module_name",
            "command",
        }
        missing_slurm = required_slurm - set(slurm)
        if missing_slurm:
            raise ValueError(
                "VASP slurm config is missing: "
                + ", ".join(sorted(missing_slurm))
            )

        return value

    @staticmethod
    def _write_text(
        path: Path,
        content: str,
    ) -> None:
        path.write_text(
            content,
            encoding="utf-8",
            newline="\n",
        )

    @staticmethod
    def _safe_id(
        value: Any,
    ) -> str:
        text = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            str(value or ""),
        ).strip("._")

        if not text:
            raise ValueError(
                "Identifier cannot form a safe path"
            )

        return text

    @staticmethod
    def _string_list(
        value: Any,
    ) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, list):
            raise TypeError(
                "Decision must be a list or CSV string"
            )
        return list(dict.fromkeys(
            str(item).strip()
            for item in value
            if str(item).strip()
        ))

    @staticmethod
    def _file_sha256(
        path: Path,
    ) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            for block in iter(
                lambda: handle.read(1024 * 1024),
                b"",
            ):
                digest.update(block)

        return digest.hexdigest()
