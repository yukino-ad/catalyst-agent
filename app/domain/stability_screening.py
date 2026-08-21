from __future__ import annotations

import math
from copy import deepcopy
from itertools import combinations
from typing import Any

from app.domain.stability_data import (
    ATOMIC_RADIUS_ANG,
    DELTA_THRESHOLD_PERCENT,
    FORMATION_ENERGY_THRESHOLD_EV_ATOM,
    GAS_CONSTANT_J_MOL_K,
    H_MIX_KJMOL,
    MELTING_POINT_K,
    OMEGA_THRESHOLD,
    SUPPORTED_STABILITY_ELEMENTS,
    canonical_pair,
)


class StabilityScreeningEvaluator:
    """Apply the C7 formation-energy and delta/Omega criteria."""

    def evaluate(
        self,
        structures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(structures, list):
            raise TypeError("structures must be a list")

        if not structures:
            return self._result(
                status="stability_screening_skipped",
                structures=[],
                errors=[],
            )

        evaluated: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for source in structures:
            structure = deepcopy(source)

            try:
                composition = self._validate(structure)
                fractions = self._fractions(composition)
                thermodynamics = self._thermodynamics(
                    fractions
                )

                formation_status = structure.get(
                    "formation_energy_status"
                )
                formation_energy = structure.get(
                    "formation_energy"
                )

                energy_available = (
                    formation_status
                    in {"predicted", "dft_completed"}
                    and isinstance(
                        formation_energy,
                        (int, float),
                    )
                    and not isinstance(
                        formation_energy,
                        bool,
                    )
                    and math.isfinite(
                        float(formation_energy)
                    )
                )

                if energy_available:
                    formation_pass = (
                        float(formation_energy)
                        < FORMATION_ENERGY_THRESHOLD_EV_ATOM
                    )
                else:
                    formation_pass = None

                solid_solution_pass = (
                    thermodynamics["delta_pass"]
                    and thermodynamics["omega_pass"]
                )

                if formation_pass is None:
                    decision = "waiting_for_formation_energy"
                    eligible = False
                elif formation_pass and solid_solution_pass:
                    decision = "passed"
                    eligible = True
                else:
                    decision = "failed"
                    eligible = False

                structure.update({
                    **thermodynamics,
                    "formation_energy_threshold_ev_atom": (
                        FORMATION_ENERGY_THRESHOLD_EV_ATOM
                    ),
                    "formation_energy_available": (
                        energy_available
                    ),
                    "formation_energy_pass": formation_pass,
                    "solid_solution_pass": (
                        solid_solution_pass
                    ),
                    "stability_decision": decision,
                    "eligible_for_slab": eligible,
                    "stability_status": (
                        "evaluated"
                        if formation_pass is not None
                        else "pending"
                    ),
                })

            except Exception as error:
                structure.update({
                    "formation_energy_pass": None,
                    "solid_solution_pass": False,
                    "stability_decision": "evaluation_failed",
                    "eligible_for_slab": False,
                    "stability_status": "failed",
                })

                errors.append({
                    "structure_id": structure.get(
                        "structure_id",
                        "",
                    ),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })

            evaluated.append(structure)

        return self._result(
            status=self._status(evaluated),
            structures=evaluated,
            errors=errors,
        )

    @staticmethod
    def _validate(
        structure: dict[str, Any],
    ) -> dict[str, int]:
        if not isinstance(structure, dict):
            raise TypeError(
                "Each structure must be a dictionary"
            )

        if not str(
            structure.get("structure_id", "")
        ).strip():
            raise ValueError("structure_id is required")

        composition = structure.get("composition")
        if not isinstance(composition, dict):
            raise TypeError(
                "composition must be a dictionary"
            )

        if not composition:
            raise ValueError("composition cannot be empty")

        unsupported = sorted(
            set(composition)
            - SUPPORTED_STABILITY_ELEMENTS
        )
        if unsupported:
            raise ValueError(
                "Missing C7 data for elements: "
                + ", ".join(unsupported)
            )

        if any(
            not isinstance(count, int)
            or isinstance(count, bool)
            or count <= 0
            for count in composition.values()
        ):
            raise ValueError(
                "composition counts must be positive integers"
            )

        return composition

    @staticmethod
    def _fractions(
        composition: dict[str, int],
    ) -> dict[str, float]:
        total = sum(composition.values())

        return {
            element: count / total
            for element, count in composition.items()
        }

    @staticmethod
    def _thermodynamics(
        fractions: dict[str, float],
    ) -> dict[str, Any]:
        average_radius = sum(
            fraction * ATOMIC_RADIUS_ANG[element]
            for element, fraction in fractions.items()
        )

        delta = 100.0 * math.sqrt(sum(
            fraction * (
                1.0
                - ATOMIC_RADIUS_ANG[element]
                / average_radius
            ) ** 2
            for element, fraction in fractions.items()
        ))

        average_melting_point = sum(
            fraction * MELTING_POINT_K[element]
            for element, fraction in fractions.items()
        )

        mixing_enthalpy = sum(
            4.0
            * fractions[first]
            * fractions[second]
            * H_MIX_KJMOL[
                canonical_pair(first, second)
            ]
            for first, second in combinations(
                fractions,
                2,
            )
        )

        mixing_entropy = -GAS_CONSTANT_J_MOL_K * sum(
            fraction * math.log(fraction)
            for fraction in fractions.values()
            if fraction > 0
        )

        omega = (
            average_melting_point
            * mixing_entropy
            / (
                max(abs(mixing_enthalpy), 1e-12)
                * 1000.0
            )
        )

        delta_pass = (
            delta <= DELTA_THRESHOLD_PERCENT
        )
        omega_pass = omega >= OMEGA_THRESHOLD

        return {
            "average_atomic_radius_ang": average_radius,
            "average_melting_point_k": (
                average_melting_point
            ),
            "mixing_enthalpy_kj_mol": mixing_enthalpy,
            "mixing_entropy_j_mol_k": mixing_entropy,
            "delta_percent": delta,
            "omega": omega,
            "delta_threshold_percent": (
                DELTA_THRESHOLD_PERCENT
            ),
            "omega_threshold": OMEGA_THRESHOLD,
            "delta_pass": delta_pass,
            "omega_pass": omega_pass,
        }

    @staticmethod
    def _status(
        structures: list[dict[str, Any]],
    ) -> str:
        decisions = {
            structure.get("stability_decision")
            for structure in structures
        }

        if decisions == {"passed"}:
            return "stability_screening_completed_all_passed"

        if decisions <= {"passed", "failed"}:
            return "stability_screening_completed"

        if decisions == {"waiting_for_formation_energy"}:
            return "stability_screening_waiting_for_energy"

        if decisions == {"evaluation_failed"}:
            return "stability_screening_failed"

        return "stability_screening_partial"

    @staticmethod
    def _result(
        status: str,
        structures: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        passed = [
            structure
            for structure in structures
            if structure.get("stability_decision")
            == "passed"
        ]

        failed_count = sum(
            structure.get("stability_decision")
            == "failed"
            for structure in structures
        )
        pending_count = sum(
            structure.get("stability_decision")
            == "waiting_for_formation_energy"
            for structure in structures
        )

        return {
            "schema_version": "c7.0",
            "stage": "c7",
            "status": status,
            "structure_count": len(structures),
            "passed_count": len(passed),
            "failed_count": failed_count,
            "pending_count": pending_count,
            "evaluation_error_count": len(errors),
            "structures": structures,
            "slab_eligible_structures": passed,
            "errors": errors,
            "criteria": {
                "formation_energy": (
                    "< 0.05 eV/atom"
                ),
                "atomic_size_delta": "≤ 6.6%",
                "omega": "≥ 1.1",
                "all_required": True,
            },
            "slab_generated": False,
            "next_stage": "c8_slab_generation",
        }