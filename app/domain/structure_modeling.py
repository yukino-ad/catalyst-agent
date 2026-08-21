from __future__ import annotations

import hashlib
from typing import Any

from tools.structure_builder import StructureBuilder


class FCCStructureModeler:
    """Build C5 FCC bulk structures from reviewed candidates."""

    MAX_CANDIDATES = 3

    def __init__(
        self,
        builder: StructureBuilder | None = None,
    ) -> None:
        self.builder = builder or StructureBuilder(
            output_dir="data/structures",
        )

    def model_candidates(
        self,
        selected_candidates: list[dict[str, Any]],
        structures_per_candidate: int = 1,
        base_seed: int = 42,
    ) -> dict[str, Any]:
        if not isinstance(selected_candidates, list):
            raise TypeError(
                "selected_candidates must be a list"
            )

        if (
            not isinstance(structures_per_candidate, int)
            or isinstance(structures_per_candidate, bool)
            or structures_per_candidate <= 0
        ):
            raise ValueError(
                "structures_per_candidate must be "
                "a positive integer"
            )

        if len(selected_candidates) > self.MAX_CANDIDATES:
            raise ValueError(
                "C5 can model at most 3 reviewed candidates."
            )

        if not selected_candidates:
            return self._result(
                status="structure_modeling_skipped",
                selected_candidate_count=0,
                modeled_candidate_count=0,
                structures=[],
                failures=[],
            )

        structures: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        modeled_candidate_ids: set[str] = set()

        for candidate_index, candidate in enumerate(
            selected_candidates
        ):
            try:
                self._validate_candidate(candidate)

                candidate_id = str(
                    candidate["candidate_id"]
                )
                seed = self._candidate_seed(
                    base_seed,
                    candidate_id,
                )
                start_index = (
                    candidate_index
                    * structures_per_candidate
                    + 1
                )

                build_result = self.builder.generate(
                    selected_elements=candidate["elements"],
                    composition=candidate["composition"],
                    generation_mode="composition_driven",
                    num_structures=structures_per_candidate,
                    start_index=start_index,
                    seed=seed,
                    min_distance=1.8,
                    unique_only=True,
                    write_cif=True,
                    write_poscar=True,
                )

                if not build_result.get("success", False):
                    raise RuntimeError(
                        "StructureBuilder did not generate "
                        "all requested structures."
                    )

                for variant_index, structure in enumerate(
                    build_result.get("results", []),
                    start=1,
                ):
                    structures.append({
                        "schema_version": "c5.0",
                        "structure_id": (
                            f"{candidate_id}-fcc-"
                            f"{variant_index:02d}"
                        ),
                        "candidate_id": candidate_id,
                        "candidate_rank": candidate.get("rank"),
                        "elements": list(
                            candidate["elements"]
                        ),
                        "composition": dict(
                            candidate["composition"]
                        ),
                        "atom_count": sum(
                            candidate["composition"].values()
                        ),
                        "crystal_structure": "FCC",
                        "supercell": "2x2x2",
                        "generation_method": (
                            "composition_driven_random_"
                            "occupation"
                        ),
                        "lattice_rule": "Vegard",
                        "lattice_constant_a0": structure.get(
                            "lattice_constant_a0"
                        ),
                        "supercell_a": structure.get(
                            "supercell_a"
                        ),
                        "minimum_distance": structure.get(
                            "minimum_distance"
                        ),
                        "signature": structure.get(
                            "signature"
                        ),
                        "cif_path": structure.get("cif_path"),
                        "poscar_path": structure.get(
                            "poscar_path"
                        ),
                        "manifest_path": build_result.get(
                            "manifest_path"
                        ),
                        "formation_energy": None,
                        "stability_decision": "not_evaluated",
                        "eligible_for_slab": False,
                        "status": "bulk_structure_created",
                    })

                modeled_candidate_ids.add(candidate_id)

            except Exception as error:
                failures.append({
                    "candidate_id": (
                        candidate.get("candidate_id", "")
                        if isinstance(candidate, dict)
                        else ""
                    ),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })

        if structures and not failures:
            status = "structure_modeling_completed"
        elif structures:
            status = "structure_modeling_partial"
        else:
            status = "structure_modeling_failed"

        return self._result(
            status=status,
            selected_candidate_count=len(
                selected_candidates
            ),
            modeled_candidate_count=len(
                modeled_candidate_ids
            ),
            structures=structures,
            failures=failures,
        )

    @staticmethod
    def _validate_candidate(
        candidate: dict[str, Any],
    ) -> None:
        if not isinstance(candidate, dict):
            raise TypeError("candidate must be a dictionary")

        candidate_id = str(
            candidate.get("candidate_id", "")
        ).strip()
        if not candidate_id:
            raise ValueError(
                "candidate_id is required"
            )

        elements = candidate.get("elements")
        composition = candidate.get("composition")

        if not isinstance(elements, list):
            raise TypeError(
                "candidate elements must be a list"
            )

        if len(elements) != 5:
            raise ValueError(
                "C5 requires exactly five elements"
            )

        if not isinstance(composition, dict):
            raise TypeError(
                "candidate composition must be a dictionary"
            )

        if set(elements) != set(composition):
            raise ValueError(
                "elements and composition must contain "
                "the same element symbols"
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

        if sum(composition.values()) != 32:
            raise ValueError(
                "C5 FCC bulk structures require 32 atoms"
            )

    @staticmethod
    def _candidate_seed(
        base_seed: int,
        candidate_id: str,
    ) -> int:
        digest = hashlib.sha256(
            candidate_id.encode("utf-8")
        ).hexdigest()

        offset = int(digest[:8], 16)
        return int(base_seed) + offset

    @staticmethod
    def _result(
        status: str,
        selected_candidate_count: int,
        modeled_candidate_count: int,
        structures: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "schema_version": "c5.0",
            "stage": "c5",
            "status": status,
            "selected_candidate_count": (
                selected_candidate_count
            ),
            "modeled_candidate_count": (
                modeled_candidate_count
            ),
            "structure_count": len(structures),
            "structures": structures,
            "failure_count": len(failures),
            "failures": failures,
            "next_stage": "c6_formation_energy",
            "formation_energy_evaluated": False,
            "stability_evaluated": False,
            "slab_generated": False,
        }