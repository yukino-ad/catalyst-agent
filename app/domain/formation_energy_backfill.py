from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.stability_screening import StabilityScreeningEvaluator
from app.domain.submitted_job_repository import SubmittedJobRepository


class FormationEnergyBackfillService:
    """Calculate DFT formation energy and pass the result to C7."""

    SCHEMA_VERSION = "c11.7"
    REQUIRED_JOB_SOURCE = "c6d_bulk_formation"
    ENERGY_FIELD = "final_toten_ev"

    def __init__(
        self,
        repository: SubmittedJobRepository | None = None,
        reference_path: str | Path = "database/formation_energy_references/element_reference_energies_v1.json",
        vasp_config_path: str | Path = "configs/dft/vasp_bulk_formation_v1.json",
        output_root: str | Path = "data/formation_energy_backfill",
        stability_evaluator: StabilityScreeningEvaluator | None = None,
    ) -> None:
        self.repository = repository or SubmittedJobRepository()
        self.reference_path = Path(reference_path)
        self.vasp_config_path = Path(vasp_config_path)
        self.output_root = Path(output_root)
        self.stability_evaluator = stability_evaluator or StabilityScreeningEvaluator()

    def calculate(self, link_path: str | Path) -> dict[str, Any]:
        link = self._read_json(Path(link_path), "job link")
        return self._calculate_link(link)

    def calculate_from_record(self, slurm_job_id: str) -> dict[str, Any]:
        """Backfill a completed C6D job using its persisted identity."""
        record = self.repository.get(str(slurm_job_id))
        if record is None:
            raise FileNotFoundError(f"Unknown persisted Slurm job ID: {slurm_job_id}")
        identity = record.get("scientific_identity")
        if not isinstance(identity, dict):
            raise ValueError("Persisted C6D job has no scientific_identity")
        previous_path = Path(str(record.get("formation_energy_backfill_result_path", "")))
        if previous_path.is_file():
            previous = self._read_json(previous_path, "formation-energy result")
            if previous.get("slurm_job_id") == str(slurm_job_id):
                return previous
        link = {
            "task_id": record["task_id"],
            "structure_id": identity["structure_id"],
            "candidate_id": identity.get("candidate_id", ""),
            "alloy_slurm_job_id": str(slurm_job_id),
            "job_source": record["job_source"],
            "composition": identity["composition"],
            "atom_count": identity["atom_count"],
            "alloy_energy_field": identity["energy_field"],
            "reference_data_version": identity["reference_data_version"],
            "source_poscar_path": identity.get("source_poscar_path", ""),
        }
        result = self._calculate_link(link)
        if hasattr(self.repository, "update"):
            self.repository.update(str(slurm_job_id), {
                "formation_energy_backfill_status": result["status"],
                "formation_energy_backfill_result_path": result["result_path"],
                "formation_energy_backfill_c7_path": result["c7_result_path"],
                "formation_energy_ev_atom": result["formation_energy"],
                "c7_stability_decision": result["c7_stability_decision"],
            })
        return result

    def _calculate_link(self, link: dict[str, Any]) -> dict[str, Any]:
        references = self._read_json(self.reference_path, "reference database")
        config = self._read_json(self.vasp_config_path, "Bulk VASP config")
        self._validate_link(link)
        self._validate_reference_header(link, references)

        slurm_job_id = str(link["alloy_slurm_job_id"])
        record = self.repository.get(slurm_job_id)
        if record is None:
            raise FileNotFoundError(f"Unknown persisted Slurm job ID: {slurm_job_id}")
        parsed = self._validate_job(record, link)
        composition = self._validate_composition(link, parsed)
        terms = self._reference_terms(
            composition, references, config.get("potcar_mapping", {})
        )

        alloy_energy = self._finite_number(
            parsed.get(self.ENERGY_FIELD),
            f"parsed_vasp_result.{self.ENERGY_FIELD}",
        )
        atom_count = sum(composition.values())
        reference_total = sum(item["total_energy_ev"] for item in terms)
        formation_energy = (alloy_energy - reference_total) / atom_count
        structure = {
            "structure_id": str(link["structure_id"]),
            "candidate_id": str(link.get("candidate_id", "")),
            "elements": list(composition),
            "composition": composition,
            "formation_energy": formation_energy,
            "formation_energy_unit": "eV/atom",
            "formation_energy_status": "dft_completed",
            "formation_energy_source": "bulk_relaxation_toten_and_user_dft_references",
            "formation_energy_method": "relaxation_final_toten",
            "source_slurm_job_id": slurm_job_id,
            "poscar_path": str(link.get("source_poscar_path", "")),
            "cif_path": None,
            "eligible_for_slab": False,
        }
        c7_result = self.stability_evaluator.evaluate([structure])
        evaluated = c7_result["structures"][0]
        result = {
            "schema_version": self.SCHEMA_VERSION,
            "stage": "formation_energy_backfill",
            "status": "formation_energy_backfill_completed",
            "task_id": str(link["task_id"]),
            "structure_id": str(link["structure_id"]),
            "candidate_id": str(link.get("candidate_id", "")),
            "slurm_job_id": slurm_job_id,
            "job_source": self.REQUIRED_JOB_SOURCE,
            "composition": composition,
            "atom_count": atom_count,
            "alloy_energy_ev": alloy_energy,
            "alloy_energy_field": self.ENERGY_FIELD,
            "reference_total_energy_ev": reference_total,
            "reference_terms": terms,
            "reference_data_version": references["data_version"],
            "reference_database": str(self.reference_path.resolve()),
            "formation_energy": formation_energy,
            "formation_energy_unit": "eV/atom",
            "formation_energy_status": "dft_completed",
            "calculation_method": "relaxation_final_toten",
            "static_single_point_used": False,
            "eligible_for_c7_backfill": True,
            "c7_formation_energy_pass": evaluated.get("formation_energy_pass"),
            "c7_stability_decision": evaluated.get("stability_decision"),
            "eligible_for_slab": evaluated.get("eligible_for_slab", False),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "remote_operation_performed": False,
            "automatic_retry_performed": False,
            "backfilled_structure": evaluated,
            "c7_result": c7_result,
        }
        paths = self._write_results(slurm_job_id, result, c7_result)
        result.update(paths)
        return result

    @staticmethod
    def _read_json(path: Path, label: str) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError(f"{label} must contain a JSON object")
        return value

    def _validate_link(self, link: dict[str, Any]) -> None:
        required = {
            "task_id", "structure_id", "alloy_slurm_job_id", "job_source",
            "composition", "atom_count", "alloy_energy_field",
            "reference_data_version",
        }
        missing = sorted(required - set(link))
        if missing:
            raise ValueError("Job link is missing: " + ", ".join(missing))
        if link["job_source"] != self.REQUIRED_JOB_SOURCE:
            raise ValueError("Job link is not a C6D Bulk formation job")
        if link["alloy_energy_field"] != self.ENERGY_FIELD:
            raise ValueError("C11.7 only supports final relaxation TOTEN")

    @staticmethod
    def _validate_reference_header(link: dict[str, Any], values: dict[str, Any]) -> None:
        if values.get("status") != "accepted":
            raise ValueError("Reference database is not accepted")
        if values.get("energy_unit") != "eV/atom":
            raise ValueError("Reference energy unit must be eV/atom")
        if values.get("source") != "user_calculated":
            raise ValueError("Reference energies must be user-calculated DFT data")
        if values.get("data_version") != link["reference_data_version"]:
            raise ValueError("Reference data version does not match the job link")
        if not isinstance(values.get("references"), dict):
            raise TypeError("references must be a dictionary")

    def _validate_job(self, record: dict[str, Any], link: dict[str, Any]) -> dict[str, Any]:
        if record.get("task_id") != link["task_id"]:
            raise ValueError("Persisted job task_id does not match the job link")
        if record.get("job_source") != self.REQUIRED_JOB_SOURCE:
            raise ValueError("Persisted job is not a C6D Bulk formation job")
        if record.get("scheduler_state") != "COMPLETED":
            raise ValueError("Slurm job is not completed")
        if record.get("vasp_decision") != "completed_converged":
            raise ValueError("VASP job is not marked completed and converged")
        parsed = record.get("parsed_vasp_result")
        if not isinstance(parsed, dict):
            raise ValueError("Persisted job has no parsed VASP result")
        if not parsed.get("normal_termination"):
            raise ValueError("VASP did not terminate normally")
        if not parsed.get("required_accuracy_reached"):
            raise ValueError("VASP did not reach the required accuracy")
        return parsed

    @staticmethod
    def _validate_composition(link: dict[str, Any], parsed: dict[str, Any]) -> dict[str, int]:
        source = link["composition"]
        if not isinstance(source, dict) or not source:
            raise ValueError("composition must be a non-empty dictionary")
        composition: dict[str, int] = {}
        for element, count in source.items():
            if not isinstance(element, str) or not element or not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                raise ValueError("composition contains an invalid element/count")
            composition[element] = count
        if sum(composition.values()) != link["atom_count"]:
            raise ValueError("Job-link atom count does not match composition")
        final = parsed.get("final_structure")
        if not isinstance(final, dict):
            raise ValueError("Parsed VASP result has no final structure")
        elements, counts = final.get("elements", []), final.get("counts", [])
        if len(elements) != len(counts):
            raise ValueError("Final structure elements/counts do not align")
        if dict(zip(elements, counts)) != composition:
            raise ValueError("CONTCAR composition does not match the job link")
        if final.get("atom_count") != link["atom_count"]:
            raise ValueError("CONTCAR atom count does not match the job link")
        return composition

    def _reference_terms(
        self, composition: dict[str, int], database: dict[str, Any],
        potcar_mapping: dict[str, Any],
    ) -> list[dict[str, Any]]:
        terms = []
        for element, count in composition.items():
            reference = database["references"].get(element)
            if not isinstance(reference, dict):
                raise ValueError(f"Missing reference energy for {element}")
            expected = potcar_mapping.get(element)
            if not expected:
                raise ValueError(f"Missing C6D POTCAR mapping for {element}")
            if reference.get("potcar") != expected:
                raise ValueError(
                    f"POTCAR mismatch for {element}: reference uses "
                    f"{reference.get('potcar')}, C6D uses {expected}"
                )
            energy = self._finite_number(
                reference.get("energy_ev_atom"), f"reference energy for {element}"
            )
            terms.append({
                "element": element, "atom_count": count,
                "reference_energy_ev_atom": energy, "potcar": expected,
                "total_energy_ev": count * energy,
            })
        return terms

    @staticmethod
    def _finite_number(value: Any, label: str) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError(f"{label} must be a finite number")
        return float(value)

    def _write_results(
        self, slurm_job_id: str, result: dict[str, Any], c7_result: dict[str, Any]
    ) -> dict[str, str]:
        result_dir, c7_dir = self.output_root / "results", self.output_root / "c7"
        result_dir.mkdir(parents=True, exist_ok=True)
        c7_dir.mkdir(parents=True, exist_ok=True)
        result_path, c7_path = result_dir / f"{slurm_job_id}.json", c7_dir / f"{slurm_job_id}.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        c7_path.write_text(json.dumps(c7_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"result_path": str(result_path.resolve()), "c7_result_path": str(c7_path.resolve())}
