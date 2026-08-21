from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from app.domain.bulk_dft_input_bundle import (
    BulkFormationVaspBundleService,
)
from app.domain.structure_modeling import FCCStructureModeler


TASK_ID = "c116-cu-ni-fe-au-co"
ELEMENTS = ["Cu", "Ni", "Fe", "Au", "Co"]
COMPOSITION = {
    "Cu": 8,
    "Ni": 6,
    "Fe": 6,
    "Au": 6,
    "Co": 6,
}
FILE_NAMES = (
    "POSCAR",
    "INCAR",
    "KPOINTS",
    "POTCAR",
    "vasp.slurm",
)


def _print_json(title: str, value: Any) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _queue_item(structure: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_type": "formation_energy_dft",
        "status": "waiting_for_supercomputer",
        "structure_id": structure["structure_id"],
        "candidate_id": structure["candidate_id"],
        "elements": list(structure["elements"]),
        "composition": dict(structure["composition"]),
        "cif_path": structure["cif_path"],
        "poscar_path": structure["poscar_path"],
        "unsupported_elements": ["Au"],
        "requested_property": "formation_energy_per_atom",
        "unit": "eV/atom",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _existing_job(
    service: BulkFormationVaspBundleService,
    bundle: dict[str, Any],
) -> dict[str, Any] | None:
    final_dir = service.output_root / bundle["task_id"] / bundle["bundle_id"]
    if not final_dir.exists():
        return None
    if not final_dir.is_dir():
        raise ValueError(f"Existing DFT path is not a directory: {final_dir}")

    actual = sorted(path.name for path in final_dir.iterdir() if path.is_file())
    if actual != sorted(FILE_NAMES):
        raise ValueError("Existing DFT directory does not contain exactly five files")

    preview = bundle["preview"]
    expected_text = {
        "POSCAR": preview["POSCAR"],
        "INCAR": preview["INCAR"],
        "KPOINTS": preview["KPOINTS"],
        "vasp.slurm": preview["vasp.slurm"]["full_text"],
    }
    for name, expected in expected_text.items():
        actual_text = (final_dir / name).read_text(encoding="utf-8")
        if actual_text != expected:
            raise ValueError(f"Existing {name} differs from the reviewed preview")

    potcar_digest = hashlib.sha256()
    for item in preview["POTCAR"]:
        source = Path(item["source_path"])
        if _sha256(source) != item["sha256"]:
            raise ValueError(f"POTCAR source changed after preview: {source}")
        potcar_digest.update(source.read_bytes())
    if _sha256(final_dir / "POTCAR") != potcar_digest.hexdigest():
        raise ValueError("Existing POTCAR differs from the reviewed assembly plan")

    return {
        "schema_version": "c6d.0",
        "job_id": bundle["bundle_id"],
        "structure_id": bundle["structure_id"],
        "candidate_id": bundle.get("candidate_id"),
        "job_dir": str(final_dir.resolve()),
        "files": {
            name: str((final_dir / name).resolve()) for name in FILE_NAMES
        },
        "element_order": bundle["elements"],
        "potcar_order": [
            item["potential"] for item in preview["POTCAR"]
        ],
        "preview_digest": bundle["preview_digest"],
        "file_count": 5,
        "submission_ready": True,
        "submitted": False,
        "status": "bulk_dft_input_files_already_verified",
    }


def prepare(task_id: str, finalize: bool) -> dict[str, Any]:
    candidate = {
        "candidate_id": "c116-Cu8Ni6Fe6Au6Co6",
        "rank": 1,
        "elements": ELEMENTS,
        "composition": COMPOSITION,
    }
    modeled = FCCStructureModeler().model_candidates(
        [candidate],
        structures_per_candidate=1,
        base_seed=116,
    )
    if modeled.get("status") != "structure_modeling_completed":
        raise RuntimeError(
            "C11.6 bulk structure generation failed: "
            + json.dumps(modeled.get("failures", []), ensure_ascii=False)
        )

    structure = modeled["structures"][0]
    service = BulkFormationVaspBundleService()
    preview = service.preview([_queue_item(structure)], task_id)
    bundle = preview["bundles"][0]

    potcar_plan = [
        {
            "element": item["element"],
            "potential": item["potential"],
            "source_path": item["source_path"],
            "sha256": item["sha256"],
        }
        for item in bundle["preview"]["POTCAR"]
    ]
    summary = {
        "task_id": task_id,
        "candidate_id": candidate["candidate_id"],
        "elements": ELEMENTS,
        "composition": COMPOSITION,
        "atom_count": sum(COMPOSITION.values()),
        "structure_id": structure["structure_id"],
        "cif_path": structure["cif_path"],
        "poscar_path": structure["poscar_path"],
        "bundle_id": bundle["bundle_id"],
        "preview_digest": bundle["preview_digest"],
        "potcar_plan": potcar_plan,
        "vasp_parameters_source": str(
            Path("configs/dft/vasp_bulk_formation_v1.json").resolve()
        ),
        "formal_files_written": False,
        "upload_performed": False,
        "submission_performed": False,
    }

    _print_json("C11.6 temporary bulk summary", summary)
    _print_json("INCAR", bundle["preview"]["INCAR"])
    _print_json("KPOINTS", bundle["preview"]["KPOINTS"])
    _print_json("vasp.slurm", bundle["preview"]["vasp.slurm"]["full_text"])
    _print_json("POTCAR assembly plan", potcar_plan)

    if not finalize:
        return summary

    expected = f"CONFIRM {bundle['bundle_id']}"
    confirmation = input(
        "Confirm the reviewed five files by entering "
        f"{expected}, or press Enter to stop:\n> "
    ).strip()
    if confirmation != expected:
        return {**summary, "status": "c116_finalize_deferred"}

    existing = _existing_job(service, bundle)
    if existing:
        return {
            **summary,
            "status": "dft_input_preparation_already_verified",
            "formal_files_written": True,
            "job": existing,
            "failures": [],
            "upload_performed": False,
            "submission_performed": False,
        }

    review = {
        "action": "finalize",
        "approve": [bundle["bundle_id"]],
        "reject": [],
        "defer": [],
        "file_confirmations": {
            bundle["bundle_id"]: {
                name: True for name in FILE_NAMES
            }
        },
    }
    result = service.finalize(preview, review)
    job = result["jobs"][0] if result.get("jobs") else {}
    return {
        **summary,
        "status": result.get("status"),
        "formal_files_written": bool(job),
        "job": job,
        "failures": result.get("failures", []),
        "upload_performed": False,
        "submission_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare one isolated C11.6 bulk DFT smoke-test job."
    )
    parser.add_argument("--task-id", default=TASK_ID)
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="Write the reviewed five-file directory after confirmation.",
    )
    args = parser.parse_args()
    result = prepare(args.task_id, args.finalize)
    _print_json("C11.6 result", result)


if __name__ == "__main__":
    main()
