from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from ase.build import make_supercell, surface
from ase.constraints import FixAtoms
from ase.io import read, write


class SlabGenerationService:
    """Build 48-atom FCC(111) slabs from C7-approved bulk structures."""

    MAX_STRUCTURES = 3
    VACUUM_ANGSTROM = 18.0
    MILLER_INDEX = (1, 1, 1)
    EXPECTED_ATOM_COUNT = 48

    def __init__(
        self,
        output_dir: str | Path = (
            "data/screening_and_slabs"
        ),
    ) -> None:
        self.output_dir = Path(output_dir)

    def generate(
        self,
        eligible_structures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(eligible_structures, list):
            raise TypeError(
                "eligible_structures must be a list"
            )

        if len(eligible_structures) > self.MAX_STRUCTURES:
            raise ValueError(
                "C8 can process at most 3 structures"
            )

        if not eligible_structures:
            return self._result(
                status="slab_generation_skipped",
                input_count=0,
                slabs=[],
                failures=[],
            )

        slabs: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        for structure in eligible_structures:
            try:
                slabs.append(
                    self._generate_one(structure)
                )
            except Exception as error:
                failures.append({
                    "structure_id": (
                        structure.get("structure_id", "")
                        if isinstance(structure, dict)
                        else ""
                    ),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })

        if slabs and not failures:
            status = "slab_generation_completed"
        elif slabs:
            status = "slab_generation_partial"
        else:
            status = "slab_generation_failed"

        result = self._result(
            status=status,
            input_count=len(eligible_structures),
            slabs=slabs,
            failures=failures,
        )

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        manifest_path = (
            self.output_dir / "latest_c8_result.json"
        )
        result["manifest_path"] = str(
            manifest_path.resolve()
        )
        manifest_path.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return result

    def _generate_one(
        self,
        structure: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_structure(structure)

        bulk_poscar = Path(
            str(structure["poscar_path"])
        ).resolve()

        atoms = read(
            str(bulk_poscar),
            format="vasp",
        )

        slab = surface(
            atoms,
            self.MILLER_INDEX,
            layers=2,
            vacuum=self.VACUUM_ANGSTROM,
        )
        slab = make_supercell(
            slab,
            np.eye(3, dtype=int),
        )

        z_positions = slab.positions[:, 2]
        unique_z = np.unique(
            np.round(z_positions, 3)
        )
        unique_z.sort()

        # Preserve the previously validated 48-atom slab rule.
        if len(unique_z) > 3:
            slab = slab[
                z_positions > unique_z[0] + 0.1
            ]

        if len(slab) != self.EXPECTED_ATOM_COUNT:
            raise RuntimeError(
                "C8 expected a 48-atom slab, "
                f"but generated {len(slab)} atoms"
            )

        slab.translate([
            0.0,
            0.0,
            -float(slab.positions[:, 2].min()),
        ])

        z_min = float(slab.positions[:, 2].min())
        z_max = float(slab.positions[:, 2].max())
        thickness = z_max - z_min

        cell = slab.cell.array.copy()
        cell[2] = np.array([
            0.0,
            0.0,
            thickness + self.VACUUM_ANGSTROM,
        ])
        slab.set_cell(cell, scale_atoms=False)
        slab.set_pbc([True, True, True])

        rounded_z = np.round(
            slab.positions[:, 2],
            3,
        )
        top_layer_mask = np.isclose(
            rounded_z,
            rounded_z.max(),
        )
        fixed_mask = ~top_layer_mask
        slab.set_constraint(
            FixAtoms(mask=fixed_mask)
        )

        cif_dir = self.output_dir / "cif"
        poscar_dir = self.output_dir / "POSCAR"
        cif_dir.mkdir(parents=True, exist_ok=True)
        poscar_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        stem = f"{bulk_poscar.stem}_slab111"
        cif_path = cif_dir / f"{stem}.cif"
        poscar_path = poscar_dir / f"{stem}.vasp"

        write(
            str(cif_path),
            slab,
            format="cif",
        )
        self._write_selective_poscar(
            slab,
            poscar_path,
        )

        return {
            "schema_version": "c8.0",
            "slab_id": (
                f"{structure['structure_id']}-slab111"
            ),
            "source_structure_id": structure[
                "structure_id"
            ],
            "candidate_id": structure.get(
                "candidate_id"
            ),
            "miller_index": [1, 1, 1],
            "atom_count": len(slab),
            "vacuum_angstrom": (
                self.VACUUM_ANGSTROM
            ),
            "slab_thickness_angstrom": thickness,
            "fixed_atom_count": int(
                fixed_mask.sum()
            ),
            "movable_atom_count": int(
                top_layer_mask.sum()
            ),
            "bulk_cif_path": structure.get(
                "cif_path"
            ),
            "bulk_poscar_path": str(bulk_poscar),
            "cif_path": str(cif_path.resolve()),
            "poscar_path": str(
                poscar_path.resolve()
            ),
            "source_stability_decision": (
                structure.get(
                    "stability_decision"
                )
            ),
            "status": "slab_created",
        }

    @staticmethod
    def _validate_structure(
        structure: dict[str, Any],
    ) -> None:
        if not isinstance(structure, dict):
            raise TypeError(
                "Each eligible structure must be "
                "a dictionary"
            )

        if not str(
            structure.get("structure_id", "")
        ).strip():
            raise ValueError(
                "structure_id is required"
            )

        if not structure.get(
            "eligible_for_slab",
            False,
        ):
            raise ValueError(
                "C8 only accepts structures approved by C7"
            )

        if structure.get(
            "stability_decision"
        ) != "passed":
            raise ValueError(
                "stability_decision must be passed"
            )

        poscar_path = Path(
            str(structure.get("poscar_path", ""))
        )
        if not poscar_path.is_file():
            raise FileNotFoundError(
                f"Bulk POSCAR does not exist: {poscar_path}"
            )

    @staticmethod
    def _write_selective_poscar(
        atoms: Any,
        path: Path,
    ) -> None:
        symbols = atoms.get_chemical_symbols()
        unique_elements = sorted(set(symbols))

        if "Cu" in unique_elements:
            unique_elements.remove("Cu")
            element_order = [
                "Cu",
                *unique_elements,
            ]
        else:
            element_order = unique_elements

        counts = [
            symbols.count(element)
            for element in element_order
        ]

        movable = np.ones(
            (len(atoms), 3),
            dtype=bool,
        )

        for constraint in atoms.constraints:
            if isinstance(constraint, FixAtoms):
                movable[
                    constraint.get_indices()
                ] = False

        lines = [
            "HEA_FCC_111_SLAB",
            "1.0",
        ]
        lines.extend(
            " ".join(
                f"{value:.16f}"
                for value in vector
            )
            for vector in atoms.cell.array
        )
        lines.extend([
            " ".join(element_order),
            " ".join(str(count) for count in counts),
            "Selective dynamics",
            "Direct",
        ])

        scaled = atoms.get_scaled_positions()

        # POSCAR coordinates must follow the element-count order.
        for element in element_order:
            for index, symbol in enumerate(symbols):
                if symbol != element:
                    continue

                coordinates = " ".join(
                    f"{value:.16f}"
                    for value in scaled[index]
                )
                flags = " ".join(
                    "T" if flag else "F"
                    for flag in movable[index]
                )
                lines.append(
                    f"{coordinates} {flags}"
                )

        path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _result(
        status: str,
        input_count: int,
        slabs: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "schema_version": "c8.0",
            "stage": "c8",
            "status": status,
            "input_structure_count": input_count,
            "slab_count": len(slabs),
            "failure_count": len(failures),
            "slabs": slabs,
            "failures": failures,
            "miller_index": [1, 1, 1],
            "expected_atom_count": 48,
            "vacuum_angstrom": 18.0,
            "stability_recalculated": False,
            "next_stage": "structure_visualization",
        }