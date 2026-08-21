from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from ase.io import read


class SlabQualityInspector:
    """Inspect C8 slabs before human review and DFT preparation."""

    MAX_STRUCTURES = 3
    EXPECTED_ATOM_COUNT = 48
    EXPECTED_ELEMENT_COUNT = 5
    EXPECTED_FIXED_COUNT = 32
    EXPECTED_MOVABLE_COUNT = 16
    TARGET_VACUUM_ANGSTROM = 18.0
    VACUUM_TOLERANCE_ANGSTROM = 0.5
    MINIMUM_DISTANCE_ANGSTROM = 1.8

    def __init__(
        self,
        output_dir: str | Path = "data/screening_and_slabs",
    ) -> None:
        self.output_dir = Path(output_dir)

    def inspect(
        self,
        slabs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(slabs, list):
            raise TypeError("slabs must be a list")

        if len(slabs) > self.MAX_STRUCTURES:
            raise ValueError("C9 can inspect at most 3 slabs")

        if not slabs:
            return self._result(
                status="slab_quality_skipped",
                input_count=0,
                reports=[],
                errors=[],
            )

        reports: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for slab in slabs:
            try:
                reports.append(self._inspect_one(slab))
            except Exception as error:
                errors.append({
                    "slab_id": (
                        slab.get("slab_id", "")
                        if isinstance(slab, dict)
                        else ""
                    ),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })

        passed = [
            report
            for report in reports
            if report["quality_decision"] == "passed"
        ]

        if len(passed) == len(slabs):
            status = "slab_quality_completed_all_passed"
        elif passed:
            status = "slab_quality_completed_partial"
        else:
            status = "slab_quality_failed"

        result = self._result(
            status=status,
            input_count=len(slabs),
            reports=reports,
            errors=errors,
        )

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        manifest = (
            self.output_dir
            / "latest_c9_quality_result.json"
        )
        result["manifest_path"] = str(manifest.resolve())

        manifest.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return result

    def _inspect_one(
        self,
        slab: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(slab, dict):
            raise TypeError("Each slab must be a dictionary")

        slab_id = str(slab.get("slab_id", "")).strip()
        if not slab_id:
            raise ValueError("slab_id is required")

        poscar_path = Path(
            str(slab.get("poscar_path", ""))
        ).resolve()

        if not poscar_path.is_file():
            raise FileNotFoundError(
                f"Slab POSCAR does not exist: {poscar_path}"
            )

        atoms = read(str(poscar_path), format="vasp")
        positions = np.asarray(
            atoms.positions,
            dtype=float,
        )
        cell = np.asarray(
            atoms.cell.array,
            dtype=float,
        )

        atom_count = len(atoms)
        element_count = len(
            set(atoms.get_chemical_symbols())
        )
        finite_coordinates = bool(
            np.isfinite(positions).all()
        )
        finite_cell = bool(np.isfinite(cell).all())
        cell_volume = float(abs(atoms.get_volume()))
        pbc = [bool(value) for value in atoms.pbc]

        minimum_distance = self._minimum_distance(
            atoms
        )
        vacuum = self._vacuum_thickness(
            atoms
        )

        selective = self._read_selective_dynamics(
            poscar_path=poscar_path,
            atom_count=atom_count,
        )

        checks = [
            self._check(
                "atom_count",
                atom_count == self.EXPECTED_ATOM_COUNT,
                atom_count,
                self.EXPECTED_ATOM_COUNT,
            ),
            self._check(
                "element_count",
                element_count == self.EXPECTED_ELEMENT_COUNT,
                element_count,
                self.EXPECTED_ELEMENT_COUNT,
            ),
            self._check(
                "finite_coordinates",
                finite_coordinates,
                finite_coordinates,
                True,
            ),
            self._check(
                "valid_cell",
                finite_cell and cell_volume > 0.0,
                cell_volume,
                "> 0",
            ),
            self._check(
                "periodic_boundary",
                all(pbc),
                pbc,
                [True, True, True],
            ),
            self._check(
                "minimum_distance",
                minimum_distance
                >= self.MINIMUM_DISTANCE_ANGSTROM,
                minimum_distance,
                f">= {self.MINIMUM_DISTANCE_ANGSTROM}",
            ),
            self._check(
                "vacuum_thickness",
                abs(
                    vacuum
                    - self.TARGET_VACUUM_ANGSTROM
                )
                <= self.VACUUM_TOLERANCE_ANGSTROM,
                vacuum,
                (
                    f"{self.TARGET_VACUUM_ANGSTROM} "
                    f"+/- {self.VACUUM_TOLERANCE_ANGSTROM}"
                ),
            ),
            self._check(
                "selective_dynamics",
                selective["present"],
                selective["present"],
                True,
            ),
            self._check(
                "fixed_atom_count",
                selective["fixed_atom_count"]
                == self.EXPECTED_FIXED_COUNT,
                selective["fixed_atom_count"],
                self.EXPECTED_FIXED_COUNT,
            ),
            self._check(
                "movable_atom_count",
                selective["movable_atom_count"]
                == self.EXPECTED_MOVABLE_COUNT,
                selective["movable_atom_count"],
                self.EXPECTED_MOVABLE_COUNT,
            ),
            self._check(
                "no_mixed_constraints",
                selective["mixed_atom_count"] == 0,
                selective["mixed_atom_count"],
                0,
            ),
        ]

        passed = all(
            check["passed"]
            for check in checks
        )

        return {
            **dict(slab),
            "schema_version": "c9.0",
            "stage": "c9_quality",
            "poscar_path": str(poscar_path),
            "atom_count": atom_count,
            "element_count": element_count,
            "cell_volume_angstrom3": cell_volume,
            "minimum_distance_angstrom": minimum_distance,
            "measured_vacuum_angstrom": vacuum,
            "fixed_atom_count": (
                selective["fixed_atom_count"]
            ),
            "movable_atom_count": (
                selective["movable_atom_count"]
            ),
            "mixed_constraint_atom_count": (
                selective["mixed_atom_count"]
            ),
            "checks": checks,
            "failed_checks": [
                check["name"]
                for check in checks
                if not check["passed"]
            ],
            "quality_decision": (
                "passed" if passed else "failed"
            ),
            "eligible_for_dft_review": passed,
            "visualization": {
                "format": "vasp",
                "structure_path": str(poscar_path),
                "recommended_views": [
                    "main",
                    "side",
                    "top",
                ],
            },
        }

    @staticmethod
    def _minimum_distance(atoms: Any) -> float:
        if len(atoms) < 2:
            return 0.0

        distances = atoms.get_all_distances(
            mic=True,
        )
        np.fill_diagonal(distances, np.inf)

        return float(np.min(distances))

    @staticmethod
    def _vacuum_thickness(atoms: Any) -> float:
        a_vector = atoms.cell.array[0]
        b_vector = atoms.cell.array[1]

        normal = np.cross(a_vector, b_vector)
        area = float(np.linalg.norm(normal))

        if area <= 0.0:
            raise ValueError("Invalid slab surface area")

        normal = normal / area
        cell_height = float(
            abs(atoms.get_volume()) / area
        )

        projections = atoms.positions @ normal
        slab_thickness = float(
            projections.max() - projections.min()
        )

        return cell_height - slab_thickness

    @staticmethod
    def _read_selective_dynamics(
        poscar_path: Path,
        atom_count: int,
    ) -> dict[str, Any]:
        lines = poscar_path.read_text(
            encoding="utf-8",
        ).splitlines()

        selective_index = next(
            (
                index
                for index, line in enumerate(lines)
                if line.strip().lower().startswith(
                    "selective"
                )
            ),
            None,
        )

        if selective_index is None:
            return {
                "present": False,
                "fixed_atom_count": 0,
                "movable_atom_count": 0,
                "mixed_atom_count": 0,
            }

        coordinate_start = selective_index + 2
        coordinate_lines = lines[
            coordinate_start:
            coordinate_start + atom_count
        ]

        if len(coordinate_lines) != atom_count:
            raise ValueError(
                "POSCAR coordinate count does not match atom count"
            )

        fixed = 0
        movable = 0
        mixed = 0

        for line in coordinate_lines:
            tokens = line.split()
            if len(tokens) < 6:
                raise ValueError(
                    "Selective-dynamics flags are missing"
                )

            flags = [
                token.upper()
                for token in tokens[3:6]
            ]

            if flags == ["F", "F", "F"]:
                fixed += 1
            elif flags == ["T", "T", "T"]:
                movable += 1
            else:
                mixed += 1

        return {
            "present": True,
            "fixed_atom_count": fixed,
            "movable_atom_count": movable,
            "mixed_atom_count": mixed,
        }

    @staticmethod
    def _check(
        name: str,
        passed: bool,
        actual: Any,
        expected: Any,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "passed": bool(passed),
            "actual": actual,
            "expected": expected,
        }

    @staticmethod
    def _result(
        status: str,
        input_count: int,
        reports: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        passed = [
            report
            for report in reports
            if report.get("quality_decision") == "passed"
        ]

        return {
            "schema_version": "c9.0",
            "stage": "c9_quality",
            "status": status,
            "input_slab_count": input_count,
            "checked_count": len(reports),
            "passed_count": len(passed),
            "failed_count": (
                len(reports) - len(passed)
            ),
            "error_count": len(errors),
            "reports": reports,
            "quality_passed_slabs": passed,
            "errors": errors,
            "criteria": {
                "atom_count": 48,
                "element_count": 5,
                "minimum_distance_angstrom": ">= 1.8",
                "vacuum_angstrom": "18.0 +/- 0.5",
                "fixed_atom_count": 32,
                "movable_atom_count": 16,
                "mixed_constraints": 0,
            },
            "next_stage": "c9_slab_review",
        }