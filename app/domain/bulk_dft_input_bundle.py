from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib

from app.domain.dft_input_bundle import VaspInputBundleService


class BulkFormationVaspBundleService(VaspInputBundleService):
    """Preview and finalize 32-atom bulk formation-energy jobs."""

    MAX_STRUCTURES = 3

    def __init__(
        self,
        output_root: str | Path = "data/dft_formation_inputs",
        config_path: str | Path = "configs/dft/vasp_bulk_formation_v1.json",
        pbe_root: str | Path = "database/PBE",
    ) -> None:
        super().__init__(output_root, config_path, pbe_root)

    def preview(
        self,
        dft_queue: list[dict[str, Any]],
        task_id: str,
    ) -> dict[str, Any]:
        if not isinstance(dft_queue, list):
            raise TypeError("dft_queue must be a list")
        if len(dft_queue) > self.MAX_STRUCTURES:
            raise ValueError("C6D can process at most 3 bulk structures")
        if not dft_queue:
            return {
                "schema_version": "c6d.0",
                "stage": "c6d_preview",
                "status": "bulk_dft_input_preview_skipped",
                "bundle_count": 0,
                "bundles": [],
            }

        clean_task_id = self._safe_id(task_id)
        config = self._load_config()
        bundles = [
            self._preview_one(item, clean_task_id, config)
            for item in dft_queue
        ]
        return {
            "schema_version": "c6d.0",
            "stage": "c6d_preview",
            "status": "bulk_dft_input_preview_completed",
            "task_id": clean_task_id,
            "bundle_count": len(bundles),
            "bundles": bundles,
            "formal_files_written": False,
            "requires_human_confirmation": True,
            "next_stage": "c6d_review",
        }

    def _preview_one(
        self,
        record: dict[str, Any],
        task_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_record(record)
        structure_id = str(record["structure_id"]).strip()
        bundle_id = self._safe_id(f"{structure_id}_bulk_formation")
        source = Path(str(record["poscar_path"])).resolve()
        poscar_text = source.read_text(encoding="utf-8")
        elements, counts = self._poscar_species(poscar_text)

        if len(elements) != 5:
            raise ValueError("C6D expects exactly five elements")
        if sum(counts) != 32:
            raise ValueError("C6D expects exactly 32 atoms")

        incar_text = self._build_bulk_incar(
            system_name=bundle_id,
            elements=elements,
            atom_count=sum(counts),
            config=config,
        )
        kpoints_text = "\n".join(config["kpoints"]) + "\n"
        slurm_text = self._build_slurm(bundle_id, config)
        potcar_plan = self._potcar_plan(elements, config)
        digest = self._preview_digest(
            poscar_text,
            incar_text,
            kpoints_text,
            slurm_text,
            potcar_plan,
        )

        return {
            "schema_version": "c6d.0",
            "calculation_type": "bulk_formation_relax",
            "bundle_id": bundle_id,
            "task_id": task_id,
            "structure_id": structure_id,
            "candidate_id": record.get("candidate_id"),
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
                    "tasks_per_node": config["slurm"]["tasks_per_node"],
                    "partition": config["slurm"]["partition"],
                    "module_name": config["slurm"]["module_name"],
                    "command": config["slurm"]["command"],
                    "full_text": slurm_text,
                },
            },
            "preview_digest": digest,
            "preview_version": 1,
            "formal_files_written": False,
            "requires_human_confirmation": True,
            "poscar_immutable": True,
        }

    def _finalize_one(self, bundle: dict[str, Any]) -> dict[str, Any]:
        # Reuse C10 atomic writing while translating slab identity to bulk identity.
        compatible = dict(bundle)
        compatible["slab_id"] = bundle["structure_id"]
        result = super()._finalize_one(compatible)
        result.pop("slab_id", None)
        result.update({
            "schema_version": "c6d.0",
            "calculation_type": "bulk_formation_relax",
            "structure_id": bundle["structure_id"],
            "status": "bulk_dft_input_files_created",
            "scientific_identity": {
                "structure_id": bundle["structure_id"],
                "candidate_id": bundle.get("candidate_id"),
                "calculation_type": "bulk_formation_relax",
                "composition": dict(zip(bundle["elements"], bundle["counts"])),
                "element_order": bundle["elements"],
                "atom_count": bundle["atom_count"],
                "energy_field": "final_toten_ev",
                "reference_data_version": "user-dft-reference-v1",
                "source_poscar_sha256": hashlib.sha256(
                    bundle["preview"]["POSCAR"].encode("utf-8")
                ).hexdigest(),
                "source_poscar_path": bundle["source_poscar_path"],
                "vasp_config_version": "vasp-bulk-formation-v1",
            },
        })
        return result

    @staticmethod
    def _build_bulk_incar(
        system_name: str,
        elements: list[str],
        atom_count: int,
        config: dict[str, Any],
    ) -> str:
        lines = [f"SYSTEM = {system_name}", ""]
        lines.extend(
            f"{key:<8}= {value}"
            for key, value in config["incar"].items()
        )
        magnetic = set(config["magnetic_elements"])
        if magnetic.intersection(elements):
            lines.extend([
                "",
                "ISPIN   = 2",
                f"MAGMOM  = {atom_count}*{config['magmom_per_atom']}",
            ])
        else:
            lines.extend(["", "ISPIN   = 1"])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _validate_record(record: dict[str, Any]) -> None:
        if not isinstance(record, dict):
            raise TypeError("Every C6D queue item must be a dictionary")
        if record.get("job_type") != "formation_energy_dft":
            raise ValueError("C6D only accepts formation_energy_dft records")
        if record.get("status") != "waiting_for_supercomputer":
            raise ValueError("C6D record is not waiting for supercomputer")
        if not str(record.get("structure_id", "")).strip():
            raise ValueError("structure_id is required")
        source = Path(str(record.get("poscar_path", "")))
        if not source.is_file():
            raise FileNotFoundError(f"Bulk POSCAR does not exist: {source}")
