from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from ase.io import read, write

from app.domain.llm_validation import optional_finite_float


class ExternalStructureInputService:
    """Normalize a user-provided Bulk POSCAR/CIF for the standard C7 path."""

    # Requiring an energy unit prevents stage labels such as "C7" from being
    # mistaken for a user-supplied formation energy.
    ENERGY_PATTERN = re.compile(
        r"(?:形成能|formation\s*energy)"
        r"[^+\-\d]{0,20}"
        r"(?P<energy>[+\-]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)"
        r"\s*(?:eV\s*/\s*atom|eV每原子|eV)",
        re.IGNORECASE,
    )
    QUOTED_PATH_PATTERN = re.compile(r"[\"'](?P<path>[A-Za-z]:\\[^\"']+)[\"']")
    WINDOWS_PATH_PATTERN = re.compile(
        r"(?P<path>[A-Za-z]:\\[^\r\n]+?(?:\.cif|\.vasp|\\POSCAR|(?=\s+[+\-]?\d)|$))",
        re.IGNORECASE,
    )

    def __init__(
        self,
        normalized_root: str | Path = "data/structures/POSCAR",
        normalized_cif_root: str | Path = "data/structures/cif",
    ) -> None:
        self.normalized_root = Path(normalized_root)
        self.normalized_cif_root = Path(normalized_cif_root)

    def resolve_request(
        self,
        question: str,
        supplied: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        supplied = supplied if isinstance(supplied, dict) else {}
        path = str(supplied.get("path", "")).strip()
        energy = supplied.get("formation_energy")
        if not path:
            path = self._path_from_question(question)
        if energy is None:
            energy = self._energy_from_question(question)
        requested = bool(path)
        return {
            "schema_version": "c-external-structure-v1",
            "requested": requested,
            "path": path,
            "formation_energy": energy,
            "formation_energy_status": "predicted",
            "formation_energy_source": "user_provided_prediction",
            "reason": (
                "external_structure_provided"
                if requested
                else "external_structure_path_missing"
            ),
        }

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        source = Path(str(request.get("path", "")).strip()).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"External structure does not exist: {source}")
        raw_energy = request.get("formation_energy")
        energy = optional_finite_float(
            raw_energy,
            field="formation_energy",
            minimum=-20.0,
            maximum=20.0,
        )
        atoms, source_format = self._read_structure(source)
        symbols = atoms.get_chemical_symbols()
        if len(symbols) != 32:
            raise ValueError(
                f"External Bulk structure must contain 32 atoms, found {len(symbols)}"
            )
        elements = list(dict.fromkeys(symbols))
        if len(elements) != 5:
            raise ValueError(
                f"External HEA Bulk must contain five elements, found {len(elements)}"
            )
        composition = {element: symbols.count(element) for element in elements}
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        self.normalized_root.mkdir(parents=True, exist_ok=True)
        self.normalized_cif_root.mkdir(parents=True, exist_ok=True)
        normalized = self.normalized_root / f"external_{digest}.vasp"
        normalized_cif = self.normalized_cif_root / f"external_{digest}.cif"
        write(str(normalized), atoms, format="vasp", direct=True, vasp5=True)
        write(str(normalized_cif), atoms, format="cif")
        structure_id = f"external-{digest}-fcc-01"
        structure = {
            "structure_id": structure_id,
            "candidate_id": f"external-{digest}",
            "elements": elements,
            "composition": composition,
            "atom_count": len(symbols),
            "poscar_path": str(normalized.resolve()),
            "cif_path": str(normalized_cif.resolve()),
            "source_structure_path": str(source),
            "source_structure_format": source_format,
            "formation_energy": energy,
            "formation_energy_unit": "eV/atom",
            "formation_energy_status": (
                "predicted" if energy is not None else "waiting_for_cgcnn"
            ),
            "formation_energy_source": (
                str(request.get(
                    "formation_energy_source", "user_provided_prediction"
                ))
                if energy is not None
                else "cgcnn"
            ),
            "eligible_for_slab": False,
            "external_structure_input": True,
        }
        return {
            "schema_version": "c-external-structure-v1",
            "stage": "external_structure_input",
            "status": (
                "external_structure_ready_for_c7"
                if energy is not None
                else "external_structure_ready_for_c6"
            ),
            "source_path": str(source),
            "normalized_poscar_path": str(normalized.resolve()),
            "normalized_cif_path": str(normalized_cif.resolve()),
            "source_format": source_format,
            "structure": structure,
            "next_stage": (
                "c7_stability_screening"
                if energy is not None
                else "c6_formation_energy"
            ),
        }

    @staticmethod
    def _read_structure(path: Path):
        if path.suffix.lower() == ".cif":
            return read(str(path), format="cif"), "cif"
        try:
            return read(str(path), format="vasp"), "poscar"
        except Exception as error:
            raise ValueError(
                "External structure must be a POSCAR, extensionless VASP file, "
                "*.vasp, or *.cif"
            ) from error

    def _path_from_question(self, question: str) -> str:
        quoted = self.QUOTED_PATH_PATTERN.search(str(question))
        if quoted:
            return quoted.group("path").strip()
        match = self.WINDOWS_PATH_PATTERN.search(str(question))
        if not match:
            return ""
        return match.group("path").strip().rstrip(".,;:，。；：")

    def _energy_from_question(self, question: str) -> float | None:
        match = self.ENERGY_PATTERN.search(str(question))
        if not match:
            return None
        return optional_finite_float(
            match.group("energy"),
            field="formation_energy",
            minimum=-20.0,
            maximum=20.0,
        )
