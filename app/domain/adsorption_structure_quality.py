from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from ase.io import read


class AdsorptionStructureQualityInspector:
    """Check C12.3 structures before human review."""

    SCHEMA_VERSION = "c12.4"
    MAX_STRUCTURES = 135

    def __init__(
        self,
        quality_config_path: str | Path = (
            "configs/adsorbates/"
            "adsorption_quality_v1.json"
        ),
        adsorbate_config_path: str | Path = (
            "configs/adsorbates/"
            "adsorbates_v1.json"
        ),
    ) -> None:
        self.quality_config_path = Path(
            quality_config_path
        )
        self.adsorbate_config_path = Path(
            adsorbate_config_path
        )

    def inspect(
        self,
        structures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(structures, list):
            raise TypeError(
                "structures must be a list"
            )

        if len(structures) > self.MAX_STRUCTURES:
            raise ValueError(
                f"C12.4 accepts at most "
                f"{self.MAX_STRUCTURES} structures"
            )

        if not structures:
            return self._result(
                "adsorption_quality_skipped",
                0,
                [],
                [],
            )

        quality = self._load_json(
            self.quality_config_path
        )
        library = self._load_json(
            self.adsorbate_config_path
        )

        reports = []
        errors = []

        for structure in structures:
            try:
                reports.append(
                    self._inspect_one(
                        structure,
                        quality,
                        library,
                    )
                )
            except Exception as error:
                errors.append({
                    "adsorption_structure_id": (
                        structure.get(
                            "adsorption_structure_id",
                            "",
                        )
                        if isinstance(
                            structure,
                            dict,
                        )
                        else ""
                    ),
                    "error_type": (
                        type(error).__name__
                    ),
                    "message": str(error),
                })

        passed = [
            report
            for report in reports
            if report["quality_decision"]
            == "passed"
        ]

        if passed and not errors and (
            len(passed) == len(structures)
        ):
            status = (
                "adsorption_quality_completed_all_passed"
            )
        elif passed:
            status = (
                "adsorption_quality_completed_partial"
            )
        else:
            status = (
                "adsorption_quality_failed"
            )

        return self._result(
            status,
            len(structures),
            reports,
            errors,
        )

    def _inspect_one(
        self,
        record: dict[str, Any],
        quality: dict[str, Any],
        library: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_record(record)

        poscar_path = Path(
            str(record["poscar_path"])
        ).resolve()
        metadata_path = Path(
            str(record["metadata_path"])
        ).resolve()
        clean_path = Path(
            str(record["clean_slab_source_path"])
        ).resolve()

        if not poscar_path.is_file():
            raise FileNotFoundError(
                f"POSCAR does not exist: {poscar_path}"
            )

        if not metadata_path.is_file():
            raise FileNotFoundError(
                "metadata.json does not exist: "
                f"{metadata_path}"
            )

        if (
            clean_path.name.upper()
            != "CONTCAR"
        ):
            raise ValueError(
                "Clean slab source must be CONTCAR"
            )

        if not clean_path.is_file():
            raise FileNotFoundError(
                f"CONTCAR does not exist: {clean_path}"
            )

        metadata = self._load_json(
            metadata_path
        )

        clean = read(
            str(clean_path),
            format="vasp",
        )
        combined = read(
            str(poscar_path),
            format="vasp",
        )

        clean_count = int(
            metadata["clean_slab_atom_count"]
        )
        adsorbate_count = int(
            metadata["adsorbate_atom_count"]
        )
        total_count = int(
            metadata["total_atom_count"]
        )

        adsorbate_name = str(
            metadata["adsorbate"]
        )
        adsorbate_symbols = list(
            metadata["adsorbate_symbols"]
        )

        configured = library[
            "adsorbates"
        ].get(adsorbate_name)

        if not isinstance(configured, dict):
            raise ValueError(
                f"Unknown adsorbate: "
                f"{adsorbate_name}"
            )

        combined_symbols = (
            combined.get_chemical_symbols()
        )
        clean_symbols = (
            clean.get_chemical_symbols()
        )

        clean_positions_unchanged = (
            len(combined) >= clean_count
            and np.allclose(
                combined.positions[:clean_count],
                clean.positions,
                atol=float(
                    quality[
                        "coordinate_tolerance_angstrom"
                    ]
                ),
                rtol=0.0,
            )
        )

        clean_order_unchanged = (
            combined_symbols[:clean_count]
            == clean_symbols
        )

        cell_unchanged = np.allclose(
            combined.cell.array,
            clean.cell.array,
            atol=float(
                quality[
                    "cell_tolerance_angstrom"
                ]
            ),
            rtol=0.0,
        )

        appended_symbols = (
            combined_symbols[clean_count:]
        )

        atom_count_valid = (
            len(clean) == clean_count
            and len(combined) == total_count
            and total_count
            == clean_count + adsorbate_count
        )

        single_adsorbate_valid = (
            metadata.get(
                "adsorbate_instance_count"
            ) == 1
            and metadata.get(
                "coadsorption"
            ) is False
            and metadata.get(
                "coverage_mode"
            ) == "single_adsorbate"
            and appended_symbols
            == adsorbate_symbols
            and len(appended_symbols)
            == len(
                configured["symbols"]
            )
        )

        minimum_slab_distance = (
            self._minimum_cross_distance(
                combined,
                range(clean_count),
                range(
                    clean_count,
                    len(combined),
                ),
            )
        )

        internal_error = (
            self._internal_distance_error(
                combined.positions[
                    clean_count:
                ],
                np.asarray(
                    configured[
                        "coordinates"
                    ],
                    dtype=float,
                ),
            )
        )

        normal = self._surface_normal(
            clean.cell.array
        )

        clean_projection = (
            clean.positions @ normal
        )
        adsorbate_projection = (
            combined.positions[
                clean_count:
            ] @ normal
        )

        minimum_height = float(
            adsorbate_projection.min()
            - clean_projection.max()
        )

        anchor_index = int(
            metadata["anchor_atom_index"]
        )
        expected_anchor_position = np.asarray(
            metadata["anchor_position_angstrom"],
            dtype=float,
        )
        if expected_anchor_position.shape != (3,):
            raise ValueError(
                "anchor_position_angstrom must contain three coordinates"
            )
        anchor_height = float(
            adsorbate_projection[anchor_index]
        )
        expected_height = float(
            expected_anchor_position @ normal
        )
        anchor_height_error = abs(
            anchor_height - expected_height
        )

        top_vacuum = (
            self._cell_height(clean)
            - float(
                adsorbate_projection.max()
            )
        )

        periodic_image_distance = (
            self._periodic_image_distance(
                combined.positions[
                    clean_count:
                ],
                combined.cell.array,
            )
        )

        source_flags = (
            self._selective_flags(
                clean_path,
                clean_count,
            )
        )
        generated_flags = (
            self._selective_flags(
                poscar_path,
                len(combined),
            )
        )

        constraints_preserved = (
            source_flags["present"]
            and generated_flags["present"]
            and generated_flags["flags"][
                :clean_count
            ] == source_flags["flags"]
        )

        adsorbate_movable = (
            generated_flags["present"]
            and generated_flags["flags"][
                clean_count:
            ] == [
                ["T", "T", "T"]
                for _ in range(
                    adsorbate_count
                )
            ]
        )

        checks = [
            self._check(
                "atom_count",
                atom_count_valid,
                len(combined),
                total_count,
            ),
            self._check(
                "single_adsorbate",
                single_adsorbate_valid,
                {
                    "instance_count": metadata.get(
                        "adsorbate_instance_count"
                    ),
                    "coadsorption": metadata.get(
                        "coadsorption"
                    ),
                    "symbols": appended_symbols,
                },
                {
                    "instance_count": 1,
                    "coadsorption": False,
                    "symbols": adsorbate_symbols,
                },
            ),
            self._check(
                "clean_coordinates",
                clean_positions_unchanged,
                clean_positions_unchanged,
                True,
            ),
            self._check(
                "clean_atom_order",
                clean_order_unchanged,
                clean_order_unchanged,
                True,
            ),
            self._check(
                "cell",
                cell_unchanged,
                cell_unchanged,
                True,
            ),
            self._check(
                "adsorbate_slab_distance",
                minimum_slab_distance
                >= float(
                    quality[
                        "minimum_adsorbate_slab_distance_angstrom"
                    ]
                ),
                minimum_slab_distance,
                (
                    ">= "
                    + str(
                        quality[
                            "minimum_adsorbate_slab_distance_angstrom"
                        ]
                    )
                ),
            ),
            self._check(
                "adsorbate_above_surface",
                minimum_height
                >= float(
                    quality[
                        "minimum_adsorbate_height_angstrom"
                    ]
                ),
                minimum_height,
                (
                    ">= "
                    + str(
                        quality[
                            "minimum_adsorbate_height_angstrom"
                        ]
                    )
                ),
            ),
            self._check(
                "anchor_height",
                anchor_height_error
                <= float(
                    quality[
                        "maximum_anchor_height_error_angstrom"
                    ]
                ),
                anchor_height_error,
                (
                    "<= "
                    + str(
                        quality[
                            "maximum_anchor_height_error_angstrom"
                        ]
                    )
                ),
            ),
            self._check(
                "internal_geometry",
                internal_error
                <= float(
                    quality[
                        "maximum_internal_distance_error_angstrom"
                    ]
                ),
                internal_error,
                (
                    "<= "
                    + str(
                        quality[
                            "maximum_internal_distance_error_angstrom"
                        ]
                    )
                ),
            ),
            self._check(
                "top_vacuum",
                top_vacuum
                >= float(
                    quality[
                        "minimum_top_vacuum_angstrom"
                    ]
                ),
                top_vacuum,
                (
                    ">= "
                    + str(
                        quality[
                            "minimum_top_vacuum_angstrom"
                        ]
                    )
                ),
            ),
            self._check(
                "periodic_image_distance",
                periodic_image_distance
                >= float(
                    quality[
                        "minimum_periodic_image_distance_angstrom"
                    ]
                ),
                periodic_image_distance,
                (
                    ">= "
                    + str(
                        quality[
                            "minimum_periodic_image_distance_angstrom"
                        ]
                    )
                ),
            ),
            self._check(
                "clean_constraints_preserved",
                constraints_preserved,
                constraints_preserved,
                True,
            ),
            self._check(
                "adsorbate_movable",
                adsorbate_movable,
                adsorbate_movable,
                True,
            ),
        ]

        passed = all(
            check["passed"]
            for check in checks
        )

        return {
            **dict(record),
            "schema_version": self.SCHEMA_VERSION,
            "stage": "c12.4_quality",
            "checks": checks,
            "failed_checks": [
                check["name"]
                for check in checks
                if not check["passed"]
            ],
            "minimum_adsorbate_slab_distance_angstrom": (
                minimum_slab_distance
            ),
            "minimum_adsorbate_height_angstrom": (
                minimum_height
            ),
            "anchor_height_error_angstrom": (
                anchor_height_error
            ),
            "internal_distance_error_angstrom": (
                internal_error
            ),
            "remaining_top_vacuum_angstrom": (
                top_vacuum
            ),
            "minimum_periodic_image_distance_angstrom": (
                periodic_image_distance
            ),
            "quality_decision": (
                "passed" if passed else "failed"
            ),
            "eligible_for_adsorption_review": passed,
            "quality_threshold_version": quality[
                "data_version"
            ],
            "quality_scope": (
                "initial_geometry_sanity_only"
            ),
        }

    @staticmethod
    def _validate_record(
        record: dict[str, Any],
    ) -> None:
        if not isinstance(record, dict):
            raise TypeError(
                "Every structure must be a dictionary"
            )

        required = {
            "adsorption_structure_id",
            "adsorbate",
            "poscar_path",
            "metadata_path",
            "clean_slab_source_path",
            "adsorbate_instance_count",
            "coadsorption",
            "eligible_for_c12_4_quality",
        }

        missing = sorted(
            required - set(record)
        )

        if missing:
            raise ValueError(
                "C12.3 structure is missing: "
                + ", ".join(missing)
            )

        if (
            record["eligible_for_c12_4_quality"]
            is not True
        ):
            raise ValueError(
                "Structure is not eligible for C12.4"
            )

        if (
            record["adsorbate_instance_count"]
            != 1
            or record["coadsorption"] is not False
        ):
            raise ValueError(
                "C12.4 only accepts one adsorbate instance"
            )

    @staticmethod
    def _minimum_cross_distance(
        atoms: Any,
        first: range,
        second: range,
    ) -> float:
        values = []

        for first_index in first:
            for second_index in second:
                values.append(
                    atoms.get_distance(
                        first_index,
                        second_index,
                        mic=True,
                    )
                )

        return float(min(values))

    @staticmethod
    def _internal_distance_error(
        actual: np.ndarray,
        expected: np.ndarray,
    ) -> float:
        if len(actual) <= 1:
            return 0.0

        errors = []

        for first in range(len(actual)):
            for second in range(
                first + 1,
                len(actual),
            ):
                actual_distance = float(
                    np.linalg.norm(
                        actual[first]
                        - actual[second]
                    )
                )
                expected_distance = float(
                    np.linalg.norm(
                        expected[first]
                        - expected[second]
                    )
                )
                errors.append(
                    abs(
                        actual_distance
                        - expected_distance
                    )
                )

        return max(errors, default=0.0)

    @staticmethod
    def _surface_normal(
        cell: np.ndarray,
    ) -> np.ndarray:
        normal = np.cross(
            cell[0],
            cell[1],
        )
        normal = (
            normal / np.linalg.norm(normal)
        )

        if normal[2] < 0:
            normal = -normal

        return normal

    @staticmethod
    def _cell_height(atoms: Any) -> float:
        first = atoms.cell.array[0]
        second = atoms.cell.array[1]
        area = float(
            np.linalg.norm(
                np.cross(first, second)
            )
        )

        return float(
            abs(atoms.get_volume()) / area
        )

    @staticmethod
    def _periodic_image_distance(
        positions: np.ndarray,
        cell: np.ndarray,
    ) -> float:
        minimum = float("inf")

        for shift_a in (-1, 0, 1):
            for shift_b in (-1, 0, 1):
                if shift_a == 0 and shift_b == 0:
                    continue

                shift = (
                    shift_a * cell[0]
                    + shift_b * cell[1]
                )

                for first in positions:
                    for second in positions:
                        minimum = min(
                            minimum,
                            float(
                                np.linalg.norm(
                                    first
                                    - (second + shift)
                                )
                            ),
                        )

        return minimum

    @staticmethod
    def _selective_flags(
        path: Path,
        atom_count: int,
    ) -> dict[str, Any]:
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()

        index = next(
            (
                line_index
                for line_index, line
                in enumerate(lines)
                if line.strip().lower().startswith(
                    "selective"
                )
            ),
            None,
        )

        if index is None:
            return {
                "present": False,
                "flags": [],
            }

        start = index + 2
        coordinates = lines[
            start:start + atom_count
        ]

        if len(coordinates) != atom_count:
            raise ValueError(
                "Selective-dynamics coordinate count "
                "does not match atom count"
            )

        flags = []

        for line in coordinates:
            tokens = line.split()

            if len(tokens) < 6:
                raise ValueError(
                    "Selective-dynamics flags are missing"
                )

            flags.append([
                token.upper()
                for token in tokens[3:6]
            ])

        return {
            "present": True,
            "flags": flags,
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
    def _load_json(
        path: Path,
    ) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(
                f"JSON file does not exist: {path}"
            )

        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(value, dict):
            raise TypeError(
                f"JSON root must be an object: {path}"
            )

        return value

    @classmethod
    def _result(
        cls,
        status: str,
        input_count: int,
        reports: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        passed = [
            report
            for report in reports
            if report.get(
                "quality_decision"
            ) == "passed"
        ]

        return {
            "schema_version": cls.SCHEMA_VERSION,
            "stage": "c12.4_quality",
            "status": status,
            "input_structure_count": input_count,
            "checked_count": len(reports),
            "passed_count": len(passed),
            "failed_count": (
                len(reports) - len(passed)
            ),
            "error_count": len(errors),
            "reports": reports,
            "quality_passed_structures": passed,
            "errors": errors,
            "quality_scope": (
                "initial_geometry_sanity_only"
            ),
            "requires_human_confirmation": bool(
                passed
            ),
            "next_stage": (
                "c12.4_adsorption_structure_review"
            ),
        }
