from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.io import read, write


class AdsorbateStructureBuilder:
    """Build one-adsorbate structures from C12.2 sites."""

    SCHEMA_VERSION = "c12.3"
    MAX_SITES = 45
    MAX_STRUCTURES = 135

    SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")

    def __init__(
        self,
        config_path: str | Path = (
            "configs/adsorbates/adsorbates_v1.json"
        ),
        output_root: str | Path = (
            "data/adsorption_structures"
        ),
    ) -> None:
        self.config_path = Path(config_path)
        self.output_root = Path(output_root)

    def build(
        self,
        task_id: str,
        sites: list[dict[str, Any]],
        reaction_plan: dict[str, Any],
    ) -> dict[str, Any]:
        clean_task_id = self._safe_id(
            task_id,
            "task_id",
        )

        if not isinstance(sites, list):
            raise TypeError(
                "sites must be a list"
            )

        if not isinstance(reaction_plan, dict):
            raise TypeError(
                "reaction_plan must be a dictionary"
            )

        if len(sites) > self.MAX_SITES:
            raise ValueError(
                f"C12.3 accepts at most "
                f"{self.MAX_SITES} sites"
            )

        adsorbates = self._string_list(
            reaction_plan.get(
                "formal_adsorbates",
                [],
            )
        )

        if not reaction_plan.get(
            "ready_for_site_generation",
            False,
        ):
            return self._empty_result(
                "adsorbate_structure_generation_blocked",
                adsorbates,
                "C12.1 reaction plan is not ready.",
            )

        if not adsorbates:
            return self._empty_result(
                "adsorbate_structure_generation_blocked",
                [],
                "No formal adsorbate is available.",
            )

        if not sites:
            return self._empty_result(
                "adsorbate_structure_generation_skipped",
                adsorbates,
                "C12.2 produced no adsorption site.",
            )

        config = self._load_config()

        unknown = [
            value
            for value in adsorbates
            if value not in config["adsorbates"]
        ]

        if unknown:
            raise ValueError(
                "Missing adsorbate geometry: "
                + ", ".join(unknown)
            )

        expected_count = (
            len(sites) * len(adsorbates)
        )

        if expected_count > self.MAX_STRUCTURES:
            raise ValueError(
                f"C12.3 would generate {expected_count} "
                f"structures; maximum is "
                f"{self.MAX_STRUCTURES}"
            )

        structures = []
        failures = []

        for site in sites:
            for adsorbate in adsorbates:
                try:
                    structures.append(
                        self._build_one(
                            task_id=clean_task_id,
                            site=site,
                            adsorbate_name=adsorbate,
                            adsorbate_config=(
                                config["adsorbates"][
                                    adsorbate
                                ]
                            ),
                            data_version=config[
                                "data_version"
                            ],
                        )
                    )
                except Exception as error:
                    failures.append({
                        "site_id": (
                            site.get("site_id", "")
                            if isinstance(site, dict)
                            else ""
                        ),
                        "adsorbate": adsorbate,
                        "error_type": (
                            type(error).__name__
                        ),
                        "message": str(error),
                    })

        if structures and not failures:
            status = (
                "adsorbate_structure_generation_completed"
            )
        elif structures:
            status = (
                "adsorbate_structure_generation_partial"
            )
        else:
            status = (
                "adsorbate_structure_generation_failed"
            )

        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage": "c12.3",
            "status": status,
            "task_id": clean_task_id,
            "input_site_count": len(sites),
            "adsorbate_count": len(adsorbates),
            "expected_structure_count": (
                expected_count
            ),
            "generated_structure_count": (
                len(structures)
            ),
            "failure_count": len(failures),
            "formal_adsorbates": adsorbates,
            "structures": structures,
            "failures": failures,
            "adsorbate_instance_limit": 1,
            "coadsorption_allowed": False,
            "single_adsorbate_per_structure": True,
            "clean_slab_coordinates_modified": False,
            "remote_operation_performed": False,
            "requires_human_confirmation": True,
            "next_stage": (
                "c12.4_adsorption_structure_quality"
            ),
        }

    def _build_one(
        self,
        task_id: str,
        site: dict[str, Any],
        adsorbate_name: str,
        adsorbate_config: dict[str, Any],
        data_version: str,
    ) -> dict[str, Any]:
        self._validate_site(
            site,
            adsorbate_name,
        )

        source_path = Path(
            str(site["source_structure_path"])
        ).resolve()

        if source_path.name.upper() != "CONTCAR":
            raise ValueError(
                "C12.3 only accepts a clean-slab CONTCAR"
            )

        clean_slab = read(
            str(source_path),
            format="vasp",
        )

        clean_positions = np.asarray(
            clean_slab.positions,
            dtype=float,
        ).copy()

        clean_symbols = list(
            clean_slab.get_chemical_symbols()
        )

        clean_cell = np.asarray(
            clean_slab.cell.array,
            dtype=float,
        ).copy()

        symbols = adsorbate_config["symbols"]
        local_coordinates = np.asarray(
            adsorbate_config["coordinates"],
            dtype=float,
        )
        anchor_index = int(
            adsorbate_config["anchor_atom_index"]
        )
        height = float(
            adsorbate_config[
                "initial_height_angstrom"
            ]
        )

        self._validate_adsorbate_geometry(
            adsorbate_name=adsorbate_name,
            symbols=symbols,
            coordinates=local_coordinates,
            anchor_index=anchor_index,
            height=height,
        )

        site_coordinate = np.asarray(
            site[
                "cartesian_coordinate_angstrom"
            ],
            dtype=float,
        )

        normal, in_plane_x, in_plane_y = (
            self._surface_frame(clean_cell)
        )

        anchor_position = (
            site_coordinate
            + height * normal
        )

        relative = (
            local_coordinates
            - local_coordinates[anchor_index]
        )

        global_coordinates = np.asarray([
            anchor_position
            + coordinate[0] * in_plane_x
            + coordinate[1] * in_plane_y
            + coordinate[2] * normal
            for coordinate in relative
        ])

        adsorbate_atoms = Atoms(
            symbols=symbols,
            positions=global_coordinates,
            cell=clean_slab.cell,
            pbc=clean_slab.pbc,
        )

        combined = clean_slab.copy()
        combined.extend(adsorbate_atoms)

        self._validate_combined_structure(
            clean_slab=clean_slab,
            combined=combined,
            clean_positions=clean_positions,
            clean_symbols=clean_symbols,
            clean_cell=clean_cell,
            adsorbate_symbols=symbols,
        )

        structure_id = self._safe_id(
            (
                f"{site['site_id']}-"
                f"{adsorbate_name}"
            ),
            "structure_id",
        )

        output_directory = (
            self.output_root
            / task_id
            / self._safe_id(
                str(site["slab_id"]),
                "slab_id",
            )
            / self._safe_id(
                adsorbate_name,
                "adsorbate",
            )
            / structure_id
        )

        if output_directory.exists():
            raise FileExistsError(
                "Adsorption structure directory "
                f"already exists: {output_directory}"
            )

        output_directory.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = output_directory.with_name(
            f".{output_directory.name}."
            f"tmp-{uuid.uuid4().hex[:8]}"
        )

        temporary.mkdir()

        try:
            poscar_path = temporary / "POSCAR"

            write(
                str(poscar_path),
                combined,
                format="vasp",
                direct=True,
                sort=False,
                vasp5=True,
            )

            metadata = {
                "schema_version": self.SCHEMA_VERSION,
                "adsorption_structure_id": (
                    structure_id
                ),
                "task_id": task_id,
                "slab_id": site["slab_id"],
                "candidate_id": site.get(
                    "candidate_id",
                    "",
                ),
                "clean_slab_slurm_job_id": site[
                    "clean_slab_slurm_job_id"
                ],
                "site_id": site["site_id"],
                "site_type": site["site_type"],
                "chemistry_signature": site[
                    "chemistry_signature"
                ],
                "adsorbate": adsorbate_name,
                "adsorbate_symbols": symbols,
                "adsorbate_atom_count": len(symbols),
                "adsorbate_instance_count": 1,
                "coadsorption": False,
                "coverage_mode": "single_adsorbate",
                "clean_slab_atom_count": len(
                    clean_slab
                ),
                "total_atom_count": len(
                    combined
                ),
                "initial_height_angstrom": height,
                "anchor_atom_index": anchor_index,
                "anchor_position_angstrom": [
                    round(float(value), 10)
                    for value in anchor_position
                ],
                "clean_slab_source_path": str(
                    source_path
                ),
                "structure_source": (
                    "relaxed_clean_slab_contcar"
                ),
                "clean_slab_coordinates_unchanged": (
                    True
                ),
                "cell_unchanged": True,
                "adsorbate_geometry_status": (
                    "initial_guess_requires_review"
                ),
                "adsorbate_library_version": (
                    data_version
                ),
                "requires_human_confirmation": True,
            }

            metadata_path = (
                temporary / "metadata.json"
            )

            metadata_path.write_text(
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            temporary.rename(
                output_directory
            )

        except Exception:
            if temporary.exists():
                import shutil
                shutil.rmtree(temporary)
            raise

        final_poscar = (
            output_directory / "POSCAR"
        )
        final_metadata = (
            output_directory / "metadata.json"
        )

        return {
            **metadata,
            "poscar_path": str(
                final_poscar.resolve()
            ),
            "metadata_path": str(
                final_metadata.resolve()
            ),
            "output_directory": str(
                output_directory.resolve()
            ),
            "poscar_sha256": self._sha256(
                final_poscar
            ),
            "file_count": 2,
            "status": (
                "adsorbate_structure_created"
            ),
            "eligible_for_c12_4_quality": True,
        }

    @staticmethod
    def _surface_frame(
        cell: np.ndarray,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
    ]:
        first = np.asarray(
            cell[0],
            dtype=float,
        )
        second = np.asarray(
            cell[1],
            dtype=float,
        )

        in_plane_x = first / np.linalg.norm(
            first
        )

        normal = np.cross(
            first,
            second,
        )
        normal = normal / np.linalg.norm(
            normal
        )

        if normal[2] < 0:
            normal = -normal

        in_plane_y = np.cross(
            normal,
            in_plane_x,
        )
        in_plane_y = (
            in_plane_y
            / np.linalg.norm(in_plane_y)
        )

        return (
            normal,
            in_plane_x,
            in_plane_y,
        )

    @staticmethod
    def _validate_site(
        site: dict[str, Any],
        adsorbate_name: str,
    ) -> None:
        if not isinstance(site, dict):
            raise TypeError(
                "Every C12.2 site must be a dictionary"
            )

        required = {
            "site_id",
            "slab_id",
            "candidate_id",
            "clean_slab_slurm_job_id",
            "site_type",
            "cartesian_coordinate_angstrom",
            "chemistry_signature",
            "source_structure_path",
            "structure_source",
            "planned_adsorbates",
            "adsorbate_instance_limit",
            "coadsorption_allowed",
        }

        missing = sorted(
            required - set(site)
        )

        if missing:
            raise ValueError(
                "C12.2 site is missing: "
                + ", ".join(missing)
            )

        if (
            site["structure_source"]
            != "relaxed_clean_slab_contcar"
        ):
            raise ValueError(
                "C12.3 only accepts C12.2 sites "
                "from relaxed clean-slab CONTCAR"
            )

        if (
            site["adsorbate_instance_limit"]
            != 1
        ):
            raise ValueError(
                "adsorbate_instance_limit must be 1"
            )

        if (
            site["coadsorption_allowed"]
            is not False
        ):
            raise ValueError(
                "Coadsorption must be disabled"
            )

        if adsorbate_name not in site[
            "planned_adsorbates"
        ]:
            raise ValueError(
                f"{adsorbate_name} is not approved "
                "for this site"
            )

    @staticmethod
    def _validate_adsorbate_geometry(
        adsorbate_name: str,
        symbols: list[str],
        coordinates: np.ndarray,
        anchor_index: int,
        height: float,
    ) -> None:
        if not isinstance(symbols, list):
            raise TypeError(
                f"{adsorbate_name}.symbols "
                "must be a list"
            )

        if not symbols:
            raise ValueError(
                f"{adsorbate_name} has no atoms"
            )

        if coordinates.shape != (
            len(symbols),
            3,
        ):
            raise ValueError(
                f"{adsorbate_name} coordinates "
                "do not match symbols"
            )

        if (
            anchor_index < 0
            or anchor_index >= len(symbols)
        ):
            raise ValueError(
                f"{adsorbate_name} anchor index "
                "is invalid"
            )

        if not np.isfinite(
            coordinates
        ).all():
            raise ValueError(
                f"{adsorbate_name} coordinates "
                "must be finite"
            )

        if not np.isfinite(height) or height <= 0:
            raise ValueError(
                f"{adsorbate_name} height "
                "must be positive"
            )

    @staticmethod
    def _validate_combined_structure(
        clean_slab: Any,
        combined: Any,
        clean_positions: np.ndarray,
        clean_symbols: list[str],
        clean_cell: np.ndarray,
        adsorbate_symbols: list[str],
    ) -> None:
        clean_count = len(clean_slab)

        if (
            len(combined)
            != clean_count
            + len(adsorbate_symbols)
        ):
            raise RuntimeError(
                "Combined atom count is invalid"
            )

        combined_symbols = (
            combined.get_chemical_symbols()
        )

        if (
            combined_symbols[:clean_count]
            != clean_symbols
        ):
            raise RuntimeError(
                "Clean-slab atom order changed"
            )

        if (
            combined_symbols[clean_count:]
            != adsorbate_symbols
        ):
            raise RuntimeError(
                "Adsorbate atoms were not appended "
                "as one instance"
            )

        if not np.array_equal(
            np.asarray(
                combined.positions[:clean_count]
            ),
            clean_positions,
        ):
            raise RuntimeError(
                "Clean-slab coordinates changed"
            )

        if not np.array_equal(
            np.asarray(combined.cell.array),
            clean_cell,
        ):
            raise RuntimeError(
                "Clean-slab cell changed"
            )

    def _load_config(
        self,
    ) -> dict[str, Any]:
        if not self.config_path.is_file():
            raise FileNotFoundError(
                f"Adsorbate library does not exist: "
                f"{self.config_path}"
            )

        value = json.loads(
            self.config_path.read_text(
                encoding="utf-8"
            )
        )

        if (
            value.get("schema_version")
            != "adsorbate-library-v1"
        ):
            raise ValueError(
                "Unsupported adsorbate library schema"
            )

        if (
            value.get("status")
            != "initial_geometry_requires_review"
        ):
            raise ValueError(
                "Adsorbate library status is invalid"
            )

        if not isinstance(
            value.get("adsorbates"),
            dict,
        ):
            raise TypeError(
                "adsorbates must be a dictionary"
            )

        return value

    def _safe_id(
        self,
        value: str,
        field_name: str,
    ) -> str:
        text = str(value).strip()

        if (
            not text
            or not self.SAFE_ID.fullmatch(text)
        ):
            raise ValueError(
                f"{field_name} contains "
                "unsafe characters"
            )

        return text

    @staticmethod
    def _string_list(
        values: Any,
    ) -> list[str]:
        if not isinstance(values, list):
            raise TypeError(
                "formal_adsorbates must be a list"
            )

        return list(dict.fromkeys(
            str(value).strip()
            for value in values
            if str(value).strip()
        ))

    @staticmethod
    def _sha256(
        path: Path,
    ) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            while chunk := handle.read(
                1024 * 1024
            ):
                digest.update(chunk)

        return digest.hexdigest()

    def _empty_result(
        self,
        status: str,
        adsorbates: list[str],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage": "c12.3",
            "status": status,
            "input_site_count": 0,
            "adsorbate_count": len(adsorbates),
            "expected_structure_count": 0,
            "generated_structure_count": 0,
            "failure_count": 0,
            "formal_adsorbates": adsorbates,
            "structures": [],
            "failures": [],
            "reason": reason,
            "adsorbate_instance_limit": 1,
            "coadsorption_allowed": False,
            "single_adsorbate_per_structure": True,
            "clean_slab_coordinates_modified": False,
            "remote_operation_performed": False,
            "requires_human_confirmation": True,
            "next_stage": (
                "human_adsorption_input_review"
            ),
        }