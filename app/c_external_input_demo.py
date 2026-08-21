from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ase.io import read

from app.domain.slab_generation import SlabGenerationService
from app.domain.stability_screening import StabilityScreeningEvaluator


def _composition(poscar: Path) -> tuple[list[str], dict[str, int]]:
    atoms = read(str(poscar), format="vasp")
    symbols = atoms.get_chemical_symbols()
    elements = list(dict.fromkeys(symbols))
    return elements, {element: symbols.count(element) for element in elements}


def run_demo(
    poscar_path: str | Path,
    formation_energy: float,
    output_dir: str | Path = "data/screening_and_slabs",
) -> dict[str, Any]:
    poscar = Path(poscar_path).resolve()
    output = Path(output_dir).resolve()
    if not poscar.is_file():
        raise FileNotFoundError(f"Bulk POSCAR does not exist: {poscar}")

    elements, composition = _composition(poscar)
    structure = {
        "structure_id": "external-c-input-fcc-01",
        "candidate_id": "external-c-input",
        "elements": elements,
        "composition": composition,
        "poscar_path": str(poscar),
        "formation_energy": float(formation_energy),
        "formation_energy_unit": "eV/atom",
        "formation_energy_status": "predicted",
        "formation_energy_source": "user_provided_cgcnn_prediction",
    }
    c7 = StabilityScreeningEvaluator().evaluate([structure])
    passed = c7.get("slab_eligible_structures", [])
    c8: dict[str, Any]
    if passed:
        c8 = SlabGenerationService(output_dir=output).generate(passed)
    else:
        c8 = {
            "schema_version": "c8.0",
            "stage": "c8",
            "status": "slab_generation_waiting_for_c7",
            "input_structure_count": 0,
            "slab_count": 0,
            "failures": [],
            "reason": "C7 did not approve the external structure.",
        }

    result = {
        "schema_version": "c-external-input-demo-v1",
        "stage": "c7_c8_external_input_demo",
        "input": {
            "poscar_path": str(poscar),
            "elements": elements,
            "composition": composition,
            "formation_energy": float(formation_energy),
            "formation_energy_unit": "eV/atom",
        },
        "c7_result": c7,
        "c8_result": c8,
        "c12_status": {
            "status": "waiting_for_clean_slab_relaxed_contcar",
            "reason": (
                "C12.3 requires a clean-slab DFT-relaxed CONTCAR; "
                "a Bulk POSCAR alone cannot produce a scientifically valid "
                "adsorption-energy result."
            ),
            "next_stage": "clean_slab_dft_then_c12_adsorption",
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "external_c_input_result.json"
    manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["manifest_path"] = str(manifest)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run C7 and C8 from an external Bulk POSCAR and CGCNN energy."
    )
    parser.add_argument("poscar_path")
    parser.add_argument("formation_energy", type=float)
    parser.add_argument(
        "--output-dir",
        default="data/screening_and_slabs",
    )
    args = parser.parse_args()
    print(json.dumps(
        run_demo(args.poscar_path, args.formation_energy, args.output_dir),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
