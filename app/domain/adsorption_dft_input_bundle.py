from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.dft_input_bundle import (
    VaspInputBundleService,
)


class AdsorptionVaspInputBundleService(
    VaspInputBundleService
):
    """Prepare reviewed C12.4 structures for adsorption DFT."""

    MAX_STRUCTURES = 15

    def __init__(
        self,
        output_root: str | Path = (
            "data/adsorption_dft_inputs"
        ),
        config_path: str | Path = (
            "configs/dft/vasp_adsorption_v1.json"
        ),
        pbe_root: str | Path = "database/PBE",
    ) -> None:
        super().__init__(
            output_root=output_root,
            config_path=config_path,
            pbe_root=pbe_root,
        )

    def preview(
        self,
        approved_structures: list[dict[str, Any]],
        task_id: str,
    ) -> dict[str, Any]:
        if not isinstance(approved_structures, list):
            raise TypeError(
                "approved_structures must be a list"
            )

        if len(approved_structures) > self.MAX_STRUCTURES:
            raise ValueError(
                "C12.5 accepts at most 15 structures"
            )

        if not approved_structures:
            return {
                "schema_version": "c12.5",
                "stage": "c12.5_preview",
                "status": (
                    "adsorption_dft_preview_skipped"
                ),
                "bundle_count": 0,
                "bundles": [],
                "formal_files_written": False,
            }

        clean_task_id = self._safe_id(task_id)
        config = self._load_config()

        bundles = [
            self._preview_one_adsorption(
                structure,
                clean_task_id,
                config,
            )
            for structure in approved_structures
        ]

        return {
            "schema_version": "c12.5",
            "stage": "c12.5_preview",
            "status": (
                "adsorption_dft_preview_completed"
            ),
            "task_id": clean_task_id,
            "bundle_count": len(bundles),
            "bundles": bundles,
            "formal_files_written": False,
            "requires_human_confirmation": True,
            "submission_performed": False,
            "next_stage": "c12.5_review",
        }

    def _preview_one_adsorption(
        self,
        structure: dict[str, Any],
        task_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_adsorption_structure(structure)

        structure_id = self._safe_id(
            str(structure["adsorption_structure_id"])
        )
        source = Path(
            str(structure["poscar_path"])
        ).resolve()

        poscar_text = source.read_text(
            encoding="utf-8"
        )
        elements, counts = self._poscar_species(
            poscar_text
        )
        atom_count = sum(counts)

        metadata_path = Path(
            str(structure["metadata_path"])
        ).resolve()
        metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )

        if atom_count != int(
            metadata["total_atom_count"]
        ):
            raise ValueError(
                "POSCAR atom count differs from metadata"
            )

        incar_text = self._build_incar(
            system_name=structure_id,
            elements=elements,
            counts=counts,
            config=config,
        )
        kpoints_text = (
            "\n".join(config["kpoints"]) + "\n"
        )
        slurm_text = self._build_slurm(
            structure_id,
            config,
        )
        potcar_plan = self._potcar_plan(
            elements,
            config,
        )

        digest = self._preview_digest(
            poscar_text=poscar_text,
            incar_text=incar_text,
            kpoints_text=kpoints_text,
            slurm_text=slurm_text,
            potcar_plan=potcar_plan,
        )

        return {
            "schema_version": "c12.5",
            "bundle_id": structure_id,
            "task_id": task_id,
            "slab_id": structure_id,
            "adsorption_structure_id": structure_id,
            "candidate_id": structure.get(
                "candidate_id"
            ),
            "source_clean_slab_id": structure.get(
                "slab_id"
            ),
            "site_id": structure.get("site_id"),
            "site_type": structure.get(
                "site_type"
            ),
            "adsorbate": structure.get(
                "adsorbate"
            ),
            "adsorbate_instance_count": 1,
            "coadsorption": False,
            "source_poscar_path": str(source),
            "metadata_path": str(metadata_path),
            "elements": elements,
            "counts": counts,
            "atom_count": atom_count,
            "preview": {
                "POSCAR": poscar_text,
                "INCAR": incar_text,
                "KPOINTS": kpoints_text,
                "POTCAR": potcar_plan,
                "vasp.slurm": {
                    "job_name": structure_id,
                    "nodes": config["slurm"]["nodes"],
                    "tasks_per_node": config[
                        "slurm"
                    ]["tasks_per_node"],
                    "partition": config[
                        "slurm"
                    ]["partition"],
                    "module_name": config[
                        "slurm"
                    ]["module_name"],
                    "command": config[
                        "slurm"
                    ]["command"],
                    "full_text": slurm_text,
                },
            },
            "preview_digest": digest,
            "preview_version": 1,
            "formal_files_written": False,
            "requires_human_confirmation": True,
        }

    def finalize(
        self,
        preview: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        result = super().finalize(
            preview,
            review,
        )

        jobs_by_id = {
            bundle["bundle_id"]: bundle
            for bundle in preview.get("bundles", [])
        }

        for job in result.get("jobs", []):
            bundle = jobs_by_id[job["job_id"]]
            job.update({
                "schema_version": "c12.5",
                "job_source": "c12_5_adsorption",
                "adsorption_structure_id": bundle[
                    "adsorption_structure_id"
                ],
                "source_clean_slab_id": bundle.get(
                    "source_clean_slab_id"
                ),
                "site_id": bundle.get("site_id"),
                "site_type": bundle.get(
                    "site_type"
                ),
                "adsorbate": bundle.get(
                    "adsorbate"
                ),
                "adsorbate_instance_count": 1,
                "coadsorption": False,
                "scientific_identity": {
                    "calculation_type": (
                        "adsorption_relax"
                    ),
                    "adsorption_structure_id": bundle[
                        "adsorption_structure_id"
                    ],
                    "candidate_id": bundle.get(
                        "candidate_id"
                    ),
                    "source_clean_slab_id": bundle.get(
                        "source_clean_slab_id"
                    ),
                    "site_id": bundle.get("site_id"),
                    "site_type": bundle.get("site_type"),
                    "adsorbate": bundle.get("adsorbate"),
                    "adsorbate_instance_count": 1,
                    "coadsorption": False,
                    "atom_count": bundle["atom_count"],
                    "element_order": bundle["elements"],
                    "composition": {
                        element: count
                        for element, count in zip(
                            bundle["elements"],
                            bundle["counts"],
                        )
                    },
                    "energy_field": "final_toten_ev",
                    "source_poscar_path": bundle[
                        "source_poscar_path"
                    ],
                    "source_poscar_sha256": (
                        self._file_sha256(
                            Path(bundle[
                                "source_poscar_path"
                            ])
                        )
                    ),
                    "vasp_config_version": (
                        "vasp-adsorption-v1"
                    ),
                },
            })

        result.update({
            "schema_version": "c12.5",
            "stage": "c12.5_finalize",
            "submission_performed": False,
            "next_stage": (
                "c12.6_adsorption_dft_execution"
            ),
        })

        return result

    @staticmethod
    def _validate_adsorption_structure(
        structure: dict[str, Any],
    ) -> None:
        if not isinstance(structure, dict):
            raise TypeError(
                "Every structure must be a dictionary"
            )

        if (
            structure.get(
                "adsorption_review_status"
            )
            != "approved_for_adsorption_dft"
        ):
            raise ValueError(
                "Structure was not approved in C12.4"
            )

        if not structure.get(
            "eligible_for_adsorption_review",
            False,
        ):
            raise ValueError(
                "Structure failed C12.4 quality checks"
            )

        if (
            structure.get(
                "adsorbate_instance_count"
            )
            != 1
            or structure.get("coadsorption")
            is not False
        ):
            raise ValueError(
                "C12.5 requires exactly one adsorbate"
            )

        for field in (
            "adsorption_structure_id",
            "poscar_path",
            "metadata_path",
            "adsorbate",
        ):
            if not str(
                structure.get(field, "")
            ).strip():
                raise ValueError(
                    f"{field} is required"
                )

        if not Path(
            str(structure["poscar_path"])
        ).is_file():
            raise FileNotFoundError(
                "Adsorption POSCAR does not exist"
            )

        if not Path(
            str(structure["metadata_path"])
        ).is_file():
            raise FileNotFoundError(
                "Adsorption metadata does not exist"
            )
