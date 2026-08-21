from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.submitted_job_repository import SubmittedJobRepository


class VaspResultParser:
    TOTEN = re.compile(r"free\s+energy\s+TOTEN\s*=\s*([-+0-9.Ee]+)")
    E0 = re.compile(r"E0=\s*([-+0-9.Ee]+)")
    FORCE = re.compile(r"FORCES:\s+max atom, RMS\s+([-+0-9.Ee]+)")

    def __init__(
        self,
        repository: SubmittedJobRepository | None = None,
    ) -> None:
        self.repository = repository or SubmittedJobRepository()

    def parse(self, slurm_job_ids: list[str] | None = None) -> dict[str, Any]:
        records = self.repository.list_records()
        if slurm_job_ids is not None:
            wanted = set(slurm_job_ids)
            records = [r for r in records if r.get("slurm_job_id") in wanted]
        jobs, errors = [], []
        for record in records:
            try:
                parsed = self._parse_one(record)
                jobs.append(self.repository.update(record["slurm_job_id"], parsed))
            except Exception as error:
                errors.append({
                    "slurm_job_id": record.get("slurm_job_id"),
                    "error_type": type(error).__name__,
                    "message": str(error),
                })
        return {
            "schema_version": "c11.5.5",
            "stage": "vasp_result_parsing",
            "status": "vasp_results_parsed" if jobs and not errors else (
                "vasp_result_parsing_partial" if jobs else
                "vasp_result_parsing_empty" if not records else "vasp_result_parsing_failed"
            ),
            "parsed_count": len(jobs),
            "failed_count": len(errors),
            "jobs": jobs,
            "errors": errors,
            "next_stage": "c11.5.6_failure_diagnosis",
        }

    def _parse_one(self, record: dict[str, Any]) -> dict[str, Any]:
        root = Path(str(record.get("local_result_directory", ""))).resolve()
        if not root.is_dir():
            raise FileNotFoundError("Downloaded result directory does not exist")
        outcar = self._optional_text(root / "OUTCAR")
        oszicar = self._optional_text(root / "OSZICAR")
        contcar = root / "CONTCAR"
        energies = [float(value) for value in self.TOTEN.findall(outcar)]
        e0_values = [float(value) for value in self.E0.findall(oszicar)]
        forces = [float(value) for value in self.FORCE.findall(outcar)]
        ionic_steps = len(re.findall(r"^\s*\d+\s+F=", oszicar, flags=re.MULTILINE))
        electronic_steps = len(re.findall(r"^\s*(DAV|RMM):", oszicar, flags=re.MULTILINE))
        structure = self._parse_poscar_header(contcar) if contcar.is_file() else None
        parsed = {
            "final_toten_ev": energies[-1] if energies else None,
            "final_e0_ev": e0_values[-1] if e0_values else None,
            "max_force_ev_ang": forces[-1] if forces else None,
            "ionic_step_count": ionic_steps,
            "electronic_step_count": electronic_steps,
            "normal_termination": (
                "General timing and accounting informations for this job" in outcar
            ),
            "required_accuracy_reached": (
                "reached required accuracy" in outcar
            ),
            "final_structure": structure,
            "evidence_files": [
                name for name in ("OUTCAR", "OSZICAR", "CONTCAR")
                if (root / name).is_file()
            ],
            "units": {
                "final_toten_ev": "eV",
                "final_e0_ev": "eV",
                "max_force_ev_ang": "eV/angstrom",
            },
        }
        return {
            "parsed_vasp_result": parsed,
            "result_parsing_status": "parsed",
            "result_parsed_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _optional_text(path: Path) -> str:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _parse_poscar_header(path: Path) -> dict[str, Any]:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) < 7:
            raise ValueError("CONTCAR is incomplete")
        elements = lines[5].split()
        counts = [int(value) for value in lines[6].split()]
        if len(elements) != len(counts):
            raise ValueError("CONTCAR element/count columns differ")
        return {
            "elements": elements,
            "counts": counts,
            "atom_count": sum(counts),
            "path": str(path.resolve()),
        }
