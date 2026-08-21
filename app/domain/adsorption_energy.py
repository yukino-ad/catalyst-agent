from __future__ import annotations

import math
from typing import Any


class AdsorptionEnergyCalculator:
    """Calculate adsorption energy from three traceable energies."""

    SCHEMA_VERSION = "c12.7"

    def calculate(
        self,
        adsorption_results: list[dict[str, Any]],
        clean_slab_energies: dict[str, Any],
        reference_energies: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(adsorption_results, list):
            raise TypeError(
                "adsorption_results must be a list"
            )

        if not isinstance(clean_slab_energies, dict):
            raise TypeError(
                "clean_slab_energies must be a dictionary"
            )

        if not isinstance(reference_energies, dict):
            raise TypeError(
                "reference_energies must be a dictionary"
            )

        if not adsorption_results:
            return self._result(
                status="adsorption_energy_skipped",
                input_count=0,
                calculations=[],
                errors=[],
            )

        calculations = []
        errors = []

        for record in adsorption_results:
            try:
                calculations.append(
                    self._calculate_one(
                        record=record,
                        clean_slab_energies=(
                            clean_slab_energies
                        ),
                        reference_energies=(
                            reference_energies
                        ),
                    )
                )
            except Exception as error:
                errors.append({
                    "adsorption_structure_id": (
                        self._structure_id(record)
                    ),
                    "error_type": (
                        type(error).__name__
                    ),
                    "message": str(error),
                })

        if calculations and not errors:
            status = "adsorption_energy_calculated"
        elif calculations:
            status = "adsorption_energy_partial"
        else:
            status = "adsorption_energy_failed"

        return self._result(
            status=status,
            input_count=len(adsorption_results),
            calculations=calculations,
            errors=errors,
        )

    def _calculate_one(
        self,
        record: dict[str, Any],
        clean_slab_energies: dict[str, Any],
        reference_energies: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise TypeError(
                "Every adsorption result must be "
                "a dictionary"
            )

        if (
            record.get("job_source")
            != "c12_5_adsorption"
        ):
            raise ValueError(
                "Only C12.6 adsorption results "
                "are accepted"
            )

        if (
            record.get("vasp_decision")
            != "completed_converged"
        ):
            raise ValueError(
                "Adsorption result is not converged"
            )

        if (
            record.get("result_parsing_status")
            != "parsed"
        ):
            raise ValueError(
                "Adsorption result is not parsed"
            )

        identity = record.get(
            "scientific_identity",
            {},
        )

        structure_id = self._structure_id(record)
        adsorbate = str(
            identity.get("adsorbate", "")
        ).strip()

        if not structure_id:
            raise ValueError(
                "adsorption_structure_id is required"
            )

        if not adsorbate:
            raise ValueError(
                "adsorbate is required"
            )

        adsorbed_energy = self._finite_energy(
            record.get(
                "parsed_vasp_result",
                {},
            ).get("final_toten_ev"),
            "adsorbed_energy_ev",
        )

        source_clean_slab_id = str(
            identity.get("source_clean_slab_id", "")
        ).strip()

        if not source_clean_slab_id:
            raise ValueError(
                "source_clean_slab_id is required"
            )

        clean_energy_key = (
            source_clean_slab_id
            if source_clean_slab_id in clean_slab_energies
            else structure_id
        )

        if clean_energy_key not in clean_slab_energies:
            raise ValueError(
                "Clean slab energy is missing for "
                f"{source_clean_slab_id}"
            )

        clean_value = clean_slab_energies[clean_energy_key]
        clean_energy = self._finite_energy(
            self._resolved_energy(clean_value, "clean_slab"),
            "clean_slab_energy_ev",
        )

        reference_value = (
            reference_energies.get(
                structure_id,
                reference_energies.get(
                    adsorbate
                ),
            )
        )

        reference_energy = self._finite_energy(
            self._resolved_energy(reference_value, "reference"),
            "reference_energy_ev",
        )

        adsorption_energy = (
            adsorbed_energy
            - clean_energy
            - reference_energy
        )

        return {
            "schema_version": self.SCHEMA_VERSION,
            "adsorption_energy_id": (
                f"AE-{structure_id}"
            ),
            "adsorption_structure_id": structure_id,
            "adsorption_slurm_job_id": str(
                record.get("slurm_job_id", "")
            ),
            "candidate_id": identity.get(
                "candidate_id"
            ),
            "source_clean_slab_id": identity.get(
                "source_clean_slab_id"
            ),
            "site_id": identity.get("site_id"),
            "site_type": identity.get(
                "site_type"
            ),
            "adsorbate": adsorbate,
            "calculation": {
                "adsorbed_energy_ev": (
                    adsorbed_energy
                ),
                "clean_slab_energy_ev": (
                    clean_energy
                ),
                "reference_energy_ev": (
                    reference_energy
                ),
                "operation": (
                    "adsorbed - clean - reference"
                ),
                "substitution": (
                    f"{adsorbed_energy} - "
                    f"({clean_energy}) - "
                    f"({reference_energy})"
                ),
                "adsorption_energy_ev": (
                    adsorption_energy
                ),
            },
            "reference_energy_provenance": (
                self._energy_provenance(reference_value)
            ),
            "clean_slab_energy_provenance": (
                self._energy_provenance(clean_value)
            ),
            "adsorption_energy_ev": (
                adsorption_energy
            ),
            "energy_unit": "eV",
            "automatic_strength_evaluation_performed": False,
            "automatic_activity_evaluation_performed": False,
            "status": (
                "calculated_requires_review"
            ),
            "requires_human_confirmation": True,
        }

    @staticmethod
    def _structure_id(
        record: Any,
    ) -> str:
        if not isinstance(record, dict):
            return ""

        identity = record.get(
            "scientific_identity",
            {},
        )

        if not isinstance(identity, dict):
            identity = {}

        return str(
            identity.get(
                "adsorption_structure_id",
                record.get("job_id", ""),
            )
        ).strip()

    @staticmethod
    def _finite_energy(
        value: Any,
        field_name: str,
    ) -> float:
        if isinstance(value, bool):
            raise ValueError(
                f"{field_name} must be numeric"
            )

        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{field_name} is missing or invalid"
            ) from error

        if not math.isfinite(number):
            raise ValueError(
                f"{field_name} must be finite"
            )

        return number

    @staticmethod
    def _resolved_energy(value: Any, kind: str) -> Any:
        if not isinstance(value, dict):
            return value
        keys = (
            ("resolved_reference_energy_ev", "energy_ev")
            if kind == "reference"
            else ("clean_slab_energy_ev", "energy_ev")
        )
        for key in keys:
            if key in value:
                return value[key]
        return None

    @staticmethod
    def _energy_provenance(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {
            "resolved_energy_ev": value,
            "data_version": "legacy-unversioned",
        }

    @classmethod
    def _result(
        cls,
        status: str,
        input_count: int,
        calculations: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "stage": "c12.7_adsorption_energy",
            "status": status,
            "input_count": input_count,
            "calculated_count": len(
                calculations
            ),
            "failed_count": len(errors),
            "calculations": calculations,
            "errors": errors,
            "energy_unit": "eV",
            "automatic_strength_evaluation_performed": False,
            "automatic_activity_evaluation_performed": False,
            "requires_human_confirmation": bool(
                calculations
            ),
            "next_stage": (
                "c12.7_adsorption_energy_review"
            ),
        }
