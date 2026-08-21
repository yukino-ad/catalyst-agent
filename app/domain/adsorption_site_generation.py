from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from ase.io import read
from pymatgen.analysis.adsorption import AdsorbateSiteFinder
from pymatgen.io.ase import AseAtomsAdaptor


class AdsorptionSiteGenerationService:
    """Enumerate locally distinct sites on converged clean-slab CONTCARs."""

    SCHEMA_VERSION = "c12.2"
    MAX_SLABS = 3
    MAX_SITES_PER_TYPE = 5
    MAX_SITES_PER_SLAB = 15
    SUPPORTED_SITE_TYPES = ("ontop", "bridge", "hollow")
    SURFACE_LAYER_TOLERANCE_ANGSTROM = 0.75
    GEOMETRY_DEDUPLICATION_ANGSTROM = 0.20
    LOCAL_ENVIRONMENT_SIZE = 6

    def generate(
        self,
        slabs: list[dict[str, Any]],
        reaction_plan: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(slabs, list):
            raise TypeError("slabs must be a list")
        if not isinstance(reaction_plan, dict):
            raise TypeError("reaction_plan must be a dictionary")
        if len(slabs) > self.MAX_SLABS:
            raise ValueError(f"C12.2 can process at most {self.MAX_SLABS} slabs")

        adsorbates = self._string_list(
            reaction_plan.get("formal_adsorbates", [])
        )
        if not reaction_plan.get("ready_for_site_generation") or not adsorbates:
            return self._empty_result(
                "adsorption_site_generation_blocked",
                adsorbates,
                "C12.1 has no approved formal adsorbate queue.",
            )
        if not slabs:
            return self._empty_result(
                "adsorption_site_generation_skipped",
                adsorbates,
                "No converged clean-slab CONTCAR was provided.",
            )

        slab_results: list[dict[str, Any]] = []
        sites: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        warnings: list[str] = []
        for slab in slabs:
            try:
                result = self._generate_one(slab, adsorbates)
                slab_results.append(result)
                sites.extend(result["sites"])
                warnings.extend(
                    warning for warning in result["warnings"]
                    if warning not in warnings
                )
            except Exception as error:
                errors.append({
                    "slab_id": slab.get("slab_id", "")
                    if isinstance(slab, dict) else "",
                    "error_type": type(error).__name__,
                    "message": str(error),
                })

        status = (
            "adsorption_site_generation_completed"
            if slab_results and not errors
            else "adsorption_site_generation_partial"
            if slab_results
            else "adsorption_site_generation_failed"
        )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage": "c12.2",
            "status": status,
            "input_slab_count": len(slabs),
            "processed_slab_count": len(slab_results),
            "failed_slab_count": len(errors),
            "site_count": len(sites),
            "planned_adsorbates": adsorbates,
            "slabs": slab_results,
            "sites": sites,
            "errors": errors,
            "warnings": warnings,
            "required_structure_source": "relaxed_clean_slab_contcar",
            "original_slab_fallback_allowed": False,
            "symmetry_only_deduplication": False,
            "local_chemistry_preserved": True,
            "structure_modified": False,
            "adsorbate_placed": False,
            "adsorbate_instance_limit": 1,
            "coadsorption_allowed": False,
            "remote_operation_performed": False,
            "requires_human_confirmation": True,
            "next_stage": "c12.3_adsorbate_structure_generation",
        }

    def _generate_one(
        self,
        slab: dict[str, Any],
        adsorbates: list[str],
    ) -> dict[str, Any]:
        self._validate_slab(slab)
        slab_id = str(slab["slab_id"]).strip()
        candidate_id = str(slab["candidate_id"]).strip()
        slurm_job_id = str(slab["clean_slab_slurm_job_id"]).strip()
        source = Path(str(slab["relaxed_contcar_path"])).resolve()
        atoms = read(str(source), format="vasp")
        if not len(atoms):
            raise ValueError("Relaxed clean-slab CONTCAR contains no atoms")
        self._validate_parsed_composition(atoms, slab["parsed_final_structure"])

        original_positions = np.asarray(atoms.positions, dtype=float).copy()
        structure = AseAtomsAdaptor.get_structure(atoms)
        raw = AdsorbateSiteFinder(structure).find_adsorption_sites(
            distance=0.0,
            put_inside=True,
            symm_reduce=0.0,
            near_reduce=0.01,
            positions=self.SUPPORTED_SITE_TYPES,
        )
        surface_indices = self._surface_atom_indices(atoms)
        candidates: list[dict[str, Any]] = []
        for site_type in self.SUPPORTED_SITE_TYPES:
            for raw_index, coordinate in enumerate(raw.get(site_type, []), 1):
                candidates.append(self._site_record(
                    slab_id, candidate_id, slurm_job_id, atoms,
                    np.asarray(coordinate, dtype=float), site_type,
                    raw_index, surface_indices, source, adsorbates,
                ))

        deduplicated = self._deduplicate(candidates, atoms)
        selected, truncation = self._limit_sites(deduplicated)
        if not np.array_equal(original_positions, np.asarray(atoms.positions)):
            raise RuntimeError("C12.2 modified clean-slab coordinates")
        type_counts = {
            kind: sum(site["site_type"] == kind for site in selected)
            for kind in self.SUPPORTED_SITE_TYPES
        }
        warnings = []
        if truncation["truncated"]:
            warnings.append(
                f"{slab_id}: sites were truncated by C12.2 cost limits."
            )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "status": "adsorption_sites_generated",
            "slab_id": slab_id,
            "candidate_id": candidate_id,
            "clean_slab_slurm_job_id": slurm_job_id,
            "source_structure_path": str(source),
            "structure_source": "relaxed_clean_slab_contcar",
            "atom_count": len(atoms),
            "element_count": len(set(atoms.get_chemical_symbols())),
            "surface_atom_count": len(surface_indices),
            "raw_site_count": len(candidates),
            "deduplicated_site_count": len(deduplicated),
            "selected_site_count": len(selected),
            "site_type_counts": type_counts,
            "sites": selected,
            "truncation": truncation,
            "warnings": warnings,
            "structure_modified": False,
            "adsorbate_placed": False,
        }

    def _site_record(
        self, slab_id: str, candidate_id: str, slurm_job_id: str,
        atoms: Any, coordinate: np.ndarray, site_type: str,
        raw_index: int, surface_indices: list[int], source: Path,
        adsorbates: list[str],
    ) -> dict[str, Any]:
        fractional = self._fractional(coordinate, atoms.cell.array)
        neighbours = self._local_environment(
            atoms, coordinate, surface_indices
        )
        nearest_count = {"ontop": 1, "bridge": 2, "hollow": 3}[site_type]
        nearest = neighbours[:nearest_count]
        nearest_elements = [item["element"] for item in nearest]
        local_elements = [item["element"] for item in neighbours]
        signature = (
            f"{site_type}:{'-'.join(sorted(nearest_elements))}"
            f"|shell:{'-'.join(sorted(local_elements))}"
        )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "site_id": f"{slab_id}-{site_type}-{raw_index:03d}",
            "slab_id": slab_id,
            "candidate_id": candidate_id,
            "clean_slab_slurm_job_id": slurm_job_id,
            "site_type": site_type,
            "raw_site_index": raw_index,
            "cartesian_coordinate_angstrom": [
                round(float(value), 10) for value in coordinate
            ],
            "fractional_coordinate": [
                round(float(value), 10) for value in fractional
            ],
            "nearest_surface_atom_indices": [
                item["atom_index"] for item in nearest
            ],
            "nearest_surface_elements": nearest_elements,
            "local_environment": neighbours,
            "local_environment_elements": local_elements,
            "chemistry_signature": signature,
            "source_structure_path": str(source),
            "structure_source": "relaxed_clean_slab_contcar",
            "planned_adsorbates": list(adsorbates),
            "adsorbate_instance_limit": 1,
            "coadsorption_allowed": False,
            "approved_for_structure_generation": False,
            "requires_human_confirmation": True,
        }

    def _surface_atom_indices(self, atoms: Any) -> list[int]:
        z_values = np.asarray(atoms.positions[:, 2], dtype=float)
        maximum = float(z_values.max())
        indices = [
            index for index, value in enumerate(z_values)
            if maximum - float(value) <= self.SURFACE_LAYER_TOLERANCE_ANGSTROM
        ]
        if not indices:
            raise ValueError("No top-surface atoms were detected")
        return indices

    def _local_environment(
        self, atoms: Any, coordinate: np.ndarray, surface_indices: list[int]
    ) -> list[dict[str, Any]]:
        symbols = atoms.get_chemical_symbols()
        neighbours = []
        for atom_index in surface_indices:
            distance = self._minimum_lateral_distance(
                coordinate, np.asarray(atoms.positions[atom_index]),
                np.asarray(atoms.cell.array),
            )
            neighbours.append({
                "atom_index": atom_index,
                "element": symbols[atom_index],
                "lateral_distance_angstrom": round(distance, 10),
            })
        neighbours.sort(
            key=lambda item: (item["lateral_distance_angstrom"], item["atom_index"])
        )
        return neighbours[:self.LOCAL_ENVIRONMENT_SIZE]

    def _deduplicate(
        self, sites: list[dict[str, Any]], atoms: Any
    ) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for site in sorted(sites, key=self._site_sort_key):
            duplicate = any(
                site["site_type"] == existing["site_type"]
                and site["chemistry_signature"] == existing["chemistry_signature"]
                and self._minimum_periodic_xy_distance(
                    site["fractional_coordinate"],
                    existing["fractional_coordinate"], atoms.cell.array,
                ) <= self.GEOMETRY_DEDUPLICATION_ANGSTROM
                for existing in kept
            )
            if not duplicate:
                kept.append(site)
        return kept

    def _limit_sites(
        self, sites: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        omitted_by_type: dict[str, int] = {}
        for site_type in self.SUPPORTED_SITE_TYPES:
            matching = sorted(
                (site for site in sites if site["site_type"] == site_type),
                key=self._site_sort_key,
            )
            accepted = matching[:self.MAX_SITES_PER_TYPE]
            selected.extend(accepted)
            omitted_by_type[site_type] = len(matching) - len(accepted)
        selected.sort(key=self._site_sort_key)
        total_omitted = max(0, len(selected) - self.MAX_SITES_PER_SLAB)
        selected = selected[:self.MAX_SITES_PER_SLAB]
        for rank, site in enumerate(selected, 1):
            site["site_rank"] = rank
            site["site_id"] = f"{site['slab_id']}-{site['site_type']}-{rank:03d}"
        omitted = sum(omitted_by_type.values()) + total_omitted
        return selected, {
            "truncated": omitted > 0,
            "omitted_count": omitted,
            "omitted_by_type": omitted_by_type,
            "max_sites_per_type": self.MAX_SITES_PER_TYPE,
            "max_sites_per_slab": self.MAX_SITES_PER_SLAB,
        }

    @staticmethod
    def _validate_slab(slab: dict[str, Any]) -> None:
        if not isinstance(slab, dict):
            raise TypeError("Every slab must be a dictionary")
        for field in ("slab_id", "candidate_id"):
            if not str(slab.get(field, "")).strip():
                raise ValueError(f"{field} is required")
        slurm_job_id = str(slab.get("clean_slab_slurm_job_id", "")).strip()
        if not slurm_job_id.isdigit():
            raise ValueError("clean_slab_slurm_job_id must be numeric")
        if slab.get("clean_slab_dft_status") != "completed_converged":
            raise ValueError("Clean-slab DFT is not completed and converged")
        if slab.get("clean_slab_result_parsing_status") != "parsed":
            raise ValueError("Clean-slab result has not been parsed")
        if slab.get("approved_for_adsorption") is not True:
            raise ValueError("Clean slab is not approved for adsorption work")
        if slab.get("structure_source") != "relaxed_clean_slab_contcar":
            raise ValueError("C12.2 only accepts a relaxed clean-slab CONTCAR")
        source = Path(str(slab.get("relaxed_contcar_path", "")))
        if source.name.upper() != "CONTCAR":
            raise ValueError("C12.2 structure file must be named CONTCAR")
        if not source.is_file():
            raise FileNotFoundError(f"Relaxed clean-slab CONTCAR does not exist: {source}")
        parsed = slab.get("parsed_final_structure")
        if not isinstance(parsed, dict):
            raise ValueError("parsed_final_structure is required")
        identity = slab.get("submitted_scientific_identity")
        if not isinstance(identity, dict):
            raise ValueError("submitted_scientific_identity is required")
        if str(identity.get("slab_id", "")) != str(slab["slab_id"]):
            raise ValueError("slab_id does not match the submitted job identity")
        if str(identity.get("candidate_id", "")) != str(slab["candidate_id"]):
            raise ValueError("candidate_id does not match the submitted job identity")

    @staticmethod
    def _validate_parsed_composition(atoms: Any, parsed: dict[str, Any]) -> None:
        elements = parsed.get("elements", [])
        counts = parsed.get("counts", [])
        if not isinstance(elements, list) or not isinstance(counts, list):
            raise ValueError("Parsed CONTCAR elements/counts are invalid")
        if len(elements) != len(counts):
            raise ValueError("Parsed CONTCAR elements/counts do not align")
        expected = dict(zip(elements, counts))
        actual: dict[str, int] = {}
        for symbol in atoms.get_chemical_symbols():
            actual[symbol] = actual.get(symbol, 0) + 1
        if expected != actual or parsed.get("atom_count") != len(atoms):
            raise ValueError("Actual CONTCAR composition differs from parsed result")

    @staticmethod
    def _site_sort_key(site: dict[str, Any]) -> tuple[Any, ...]:
        order = {"ontop": 0, "bridge": 1, "hollow": 2}
        fractional = site["fractional_coordinate"]
        return (
            order.get(site["site_type"], 99), site["chemistry_signature"],
            round(float(fractional[0]), 8), round(float(fractional[1]), 8),
        )

    @staticmethod
    def _fractional(coordinate: np.ndarray, cell: np.ndarray) -> np.ndarray:
        fractional = np.linalg.solve(np.asarray(cell).T, coordinate)
        fractional[0] %= 1.0
        fractional[1] %= 1.0
        return fractional

    @staticmethod
    def _minimum_lateral_distance(
        coordinate: np.ndarray, atom_position: np.ndarray, cell: np.ndarray
    ) -> float:
        minimum = math.inf
        for first in (-1, 0, 1):
            for second in (-1, 0, 1):
                delta = coordinate - (
                    atom_position + first * cell[0] + second * cell[1]
                )
                minimum = min(minimum, float(np.linalg.norm(delta[:2])))
        return minimum

    @staticmethod
    def _minimum_periodic_xy_distance(
        first: list[float], second: list[float], cell: np.ndarray
    ) -> float:
        a = np.asarray(first, dtype=float)
        b = np.asarray(second, dtype=float)
        minimum = math.inf
        for shift_a in (-1, 0, 1):
            for shift_b in (-1, 0, 1):
                delta = a - b + np.asarray([shift_a, shift_b, 0.0])
                cartesian = delta @ np.asarray(cell, dtype=float)
                minimum = min(minimum, float(np.linalg.norm(cartesian[:2])))
        return minimum

    @staticmethod
    def _string_list(values: Any) -> list[str]:
        if not isinstance(values, list):
            raise TypeError("formal_adsorbates must be a list")
        return list(dict.fromkeys(
            str(value).strip() for value in values if str(value).strip()
        ))

    def _empty_result(
        self, status: str, adsorbates: list[str], reason: str
    ) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage": "c12.2",
            "status": status,
            "input_slab_count": 0,
            "processed_slab_count": 0,
            "failed_slab_count": 0,
            "site_count": 0,
            "planned_adsorbates": adsorbates,
            "slabs": [],
            "sites": [],
            "errors": [],
            "warnings": [],
            "reason": reason,
            "required_structure_source": "relaxed_clean_slab_contcar",
            "original_slab_fallback_allowed": False,
            "structure_modified": False,
            "adsorbate_placed": False,
            "adsorbate_instance_limit": 1,
            "coadsorption_allowed": False,
            "remote_operation_performed": False,
            "requires_human_confirmation": True,
            "next_stage": "human_adsorption_input_review",
        }
