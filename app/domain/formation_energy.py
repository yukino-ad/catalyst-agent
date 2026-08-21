from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from tools.cgcnn_service import CGCNNService


CGCNN_SUPPORTED_ELEMENTS = frozenset({
    "Al", "Co", "Cr", "Cu", "Fe", "Ga",
    "Ge", "Mn", "Mo", "Ni", "Ti", "Zn",
})


class FormationEnergyEvaluator:
    """Route C5 bulk structures to CGCNN or future DFT."""

    def __init__(
        self,
        cgcnn: CGCNNService | None = None,
    ) -> None:
        self.cgcnn = cgcnn or CGCNNService()

    def evaluate(
        self,
        bulk_structures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(bulk_structures, list):
            raise TypeError(
                "bulk_structures must be a list"
            )

        if not bulk_structures:
            return self._result(
                status="formation_energy_skipped",
                structures=[],
                dft_queue=[],
                errors=[],
            )

        evaluated = [
            deepcopy(structure)
            for structure in bulk_structures
        ]

        cgcnn_indices: list[int] = []
        cgcnn_paths: list[str] = []
        dft_queue: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for index, structure in enumerate(evaluated):
            try:
                self._validate_structure(structure)

                elements = set(structure["elements"])
                unsupported = sorted(
                    elements - CGCNN_SUPPORTED_ELEMENTS
                )

                if unsupported:
                    structure.update({
                        "formation_energy_route": (
                            "dft_required"
                        ),
                        "formation_energy_route_reason": (
                            "candidate_contains_elements_"
                            "outside_cgcnn_domain"
                        ),
                        "cgcnn_domain_supported": False,
                        "cgcnn_unsupported_elements": unsupported,
                        "formation_energy": None,
                        "formation_energy_unit": "eV/atom",
                        "formation_energy_source": None,
                        "formation_energy_status": (
                            "waiting_for_dft"
                        ),
                        "stability_decision": "not_evaluated",
                        "eligible_for_slab": False,
                    })

                    dft_queue.append(
                        self._dft_record(structure)
                    )
                    continue

                cif_path = Path(
                    str(structure["cif_path"])
                )

                if not cif_path.is_file():
                    raise FileNotFoundError(
                        f"CIF does not exist: {cif_path}"
                    )

                structure.update({
                    "formation_energy_route": "cgcnn",
                    "formation_energy_route_reason": (
                        "all_elements_inside_cgcnn_domain"
                    ),
                    "cgcnn_domain_supported": True,
                    "cgcnn_unsupported_elements": [],
                    "formation_energy": None,
                    "formation_energy_unit": "eV/atom",
                    "formation_energy_source": "cgcnn",
                    "formation_energy_status": (
                        "waiting_for_cgcnn"
                    ),
                    "stability_decision": "not_evaluated",
                    "eligible_for_slab": False,
                })

                cgcnn_indices.append(index)
                cgcnn_paths.append(str(cif_path))

            except Exception as error:
                structure.update({
                    "formation_energy_route": "invalid_input",
                    "formation_energy": None,
                    "formation_energy_unit": "eV/atom",
                    "formation_energy_source": None,
                    "formation_energy_status": "input_failed",
                    "stability_decision": "not_evaluated",
                    "eligible_for_slab": False,
                })

                errors.append({
                    "structure_id": structure.get(
                        "structure_id", ""
                    ),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })

        if cgcnn_paths:
            self._predict_cgcnn(
                evaluated= evaluated,
                structure_indices=cgcnn_indices,
                cif_paths=cgcnn_paths,
                errors=errors,
            )

        return self._result(
            status=self._resolve_status(evaluated),
            structures=evaluated,
            dft_queue=dft_queue,
            errors=errors,
        )

    def _predict_cgcnn(
        self,
        evaluated: list[dict[str, Any]],
        structure_indices: list[int],
        cif_paths: list[str],
        errors: list[dict[str, Any]],
    ) -> None:
        try:
            predictions = self.cgcnn.predict(cif_paths)

            if len(predictions) != len(structure_indices):
                raise RuntimeError(
                    "CGCNN prediction count does not match "
                    "the submitted structure count"
                )

            for index, prediction in zip(
                structure_indices,
                predictions,
            ):
                structure = evaluated[index]
                structure.update({
                    "formation_energy": float(
                        prediction[
                            "formation_energy_per_atom"
                        ]
                    ),
                    "formation_energy_unit": prediction.get(
                        "unit",
                        "eV/atom",
                    ),
                    "formation_energy_source": "cgcnn",
                    "formation_energy_status": "predicted",
                    "cgcnn_model_path": prediction.get(
                        "model_path",
                        "",
                    ),
                    "cgcnn_prediction_id": prediction.get(
                        "cif_id",
                        "",
                    ),
                    "stability_decision": "not_evaluated",
                    "eligible_for_slab": False,
                })

        except Exception as error:
            for index in structure_indices:
                structure = evaluated[index]
                structure.update({
                    "formation_energy": None,
                    "formation_energy_status": (
                        "cgcnn_prediction_failed"
                    ),
                    "stability_decision": "not_evaluated",
                    "eligible_for_slab": False,
                })

                errors.append({
                    "structure_id": structure.get(
                        "structure_id",
                        "",
                    ),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })

    @staticmethod
    def _validate_structure(
        structure: dict[str, Any],
    ) -> None:
        if not isinstance(structure, dict):
            raise TypeError(
                "Each bulk structure must be a dictionary"
            )

        if not str(
            structure.get("structure_id", "")
        ).strip():
            raise ValueError("structure_id is required")

        elements = structure.get("elements")
        if not isinstance(elements, list) or not elements:
            raise ValueError(
                "structure elements must be a non-empty list"
            )

        if not structure.get("cif_path"):
            raise ValueError("cif_path is required")

    @staticmethod
    def _dft_record(
        structure: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": "c6.0",
            "job_type": "formation_energy_dft",
            "status": "waiting_for_supercomputer",
            "structure_id": structure.get(
                "structure_id"
            ),
            "candidate_id": structure.get(
                "candidate_id"
            ),
            "elements": structure.get(
                "elements",
                [],
            ),
            "composition": structure.get(
                "composition",
                {},
            ),
            "cif_path": structure.get(
                "cif_path"
            ),
            "poscar_path": structure.get(
                "poscar_path"
            ),
            "unsupported_elements": structure.get(
                "cgcnn_unsupported_elements",
                [],
            ),
            "requested_property": (
                "formation_energy_per_atom"
            ),
            "unit": "eV/atom",
            "supercomputer_submission": (
                "not_implemented"
            ),
        }

    @staticmethod
    def _resolve_status(
        structures: list[dict[str, Any]],
    ) -> str:
        statuses = {
            structure.get("formation_energy_status")
            for structure in structures
        }

        if statuses == {"predicted"}:
            return "formation_energy_completed"

        if statuses == {"waiting_for_dft"}:
            return "formation_energy_waiting_for_dft"

        if statuses <= {
            "input_failed",
            "cgcnn_prediction_failed",
        }:
            return "formation_energy_failed"

        return "formation_energy_partial"

    @staticmethod
    def _result(
        status: str,
        structures: list[dict[str, Any]],
        dft_queue: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        predicted_count = sum(
            structure.get("formation_energy_status")
            == "predicted"
            for structure in structures
        )
        waiting_for_dft_count = sum(
            structure.get("formation_energy_status")
            == "waiting_for_dft"
            for structure in structures
        )
        failed_count = sum(
            structure.get("formation_energy_status")
            in {
                "input_failed",
                "cgcnn_prediction_failed",
            }
            for structure in structures
        )

        return {
            "schema_version": "c6.0",
            "stage": "c6",
            "status": status,
            "structure_count": len(structures),
            "cgcnn_predicted_count": predicted_count,
            "waiting_for_dft_count": waiting_for_dft_count,
            "failed_count": failed_count,
            "structures": structures,
            "dft_queue": dft_queue,
            "error_count": len(errors),
            "errors": errors,
            "formation_energy_threshold_applied": False,
            "stability_evaluated": False,
            "slab_generated": False,
            "next_stage": "c7_stability_screening",
        }