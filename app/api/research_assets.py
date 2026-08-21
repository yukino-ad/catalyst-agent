from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.domain.submitted_job_repository import SubmittedJobRepository
from app.domain.workflow_run_repository import WorkflowRunRepository


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = (PROJECT_ROOT / "data").resolve()
PREVIEW_NAMES = {
    "POSCAR", "CONTCAR", "INCAR", "KPOINTS", "OSZICAR", "OUTCAR",
    "vasp.slurm",
}
STRUCTURE_NAMES = {"POSCAR", "CONTCAR"}


class ResearchAssetService:
    """Expose task-owned local artifacts without leaking arbitrary paths."""

    def __init__(
        self,
        runs: WorkflowRunRepository | None = None,
        jobs: SubmittedJobRepository | None = None,
    ) -> None:
        self.runs = runs or WorkflowRunRepository()
        self.jobs = jobs or SubmittedJobRepository()

    def list_files(self, task_id: str) -> list[dict[str, Any]]:
        task = self._task(task_id)
        paths = self._task_paths(task_id, task)
        return [self._describe(path) for path in sorted(paths, key=str)]

    def preview(self, task_id: str, file_id: str) -> dict[str, Any]:
        path = self._resolve_file(task_id, file_id)
        if path.name == "POTCAR":
            return {
                "file_id": file_id,
                "name": path.name,
                "mode": "potcar_labels",
                "content": self._potcar_labels(path),
                "truncated": False,
            }
        if path.name not in PREVIEW_NAMES and path.suffix.lower() not in {".vasp", ".cif", ".json", ".txt", ".out"}:
            raise ValueError("This file type does not support browser preview.")
        limit = 120_000 if path.name not in {"OUTCAR", "OSZICAR"} else 40_000
        text = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > limit
        if truncated:
            text = text[-limit:]
        return {
            "file_id": file_id,
            "name": path.name,
            "mode": "tail" if truncated else "full",
            "content": text,
            "truncated": truncated,
        }

    def downloadable(self, task_id: str, file_id: str) -> Path:
        path = self._resolve_file(task_id, file_id)
        if path.name == "POTCAR":
            raise ValueError("POTCAR download is disabled because it may contain licensed data.")
        return path

    def list_structures(self, task_id: str) -> list[dict[str, Any]]:
        structures = []
        for item in self.list_files(task_id):
            if item["name"] in STRUCTURE_NAMES or item["suffix"] in {".vasp", ".cif"}:
                structures.append({
                    "structure_id": item["file_id"],
                    "name": item["name"],
                    "label": item["label"],
                    "category": item["category"],
                })
        return structures

    def structure(self, task_id: str, structure_id: str) -> dict[str, Any]:
        path = self._resolve_file(task_id, structure_id)
        if path.name not in STRUCTURE_NAMES and path.suffix.lower() not in {".vasp", ".cif"}:
            raise ValueError("Selected artifact is not a supported structure.")
        parsed = (
            self._parse_cif(path)
            if path.suffix.lower() == ".cif"
            else self._parse_poscar(path)
        )
        parsed.update({"structure_id": structure_id, "name": path.name})
        return parsed

    def structure_id_for_label(self, task_id: str, label: str) -> str:
        needle = re.sub(r"[^a-z0-9]", "", label.lower())
        structures = self.list_structures(task_id)
        for item in structures:
            candidate = re.sub(r"[^a-z0-9]", "", str(item["label"]).lower())
            if needle and (needle in candidate or candidate in needle):
                return str(item["structure_id"])
        return str(structures[0]["structure_id"]) if structures else ""

    def _task(self, task_id: str) -> dict[str, Any]:
        task = self.runs.get(task_id)
        if task is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        return task

    def _task_paths(self, task_id: str, task: dict[str, Any]) -> set[Path]:
        paths: set[Path] = set()
        tokens = self._identity_tokens(task)
        for job in self.jobs.list_records():
            if str(job.get("task_id", "")) != task_id:
                continue
            tokens.update(self._identity_tokens(job))
            self._collect_paths(job, paths)

        # Current stage manifests retain the original structure paths. Match by
        # scientific IDs before exposing any path from a shared manifest.
        manifest_roots = [
            DATA_ROOT / "screening_and_slabs",
            DATA_ROOT / "structures",
            DATA_ROOT / "cgcnn_prediction",
            DATA_ROOT / "dft_inputs",
            DATA_ROOT / "dft_formation_inputs",
            DATA_ROOT / "adsorption_structures",
            DATA_ROOT / "adsorption_dft_inputs",
        ]
        for root in manifest_roots:
            if not root.is_dir():
                continue
            for manifest in root.glob("*.json"):
                try:
                    value = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                self._collect_matching_objects(value, tokens, paths)
        return {path for path in paths if path.is_file() and self._inside_data(path)}

    def _collect_matching_objects(self, value: Any, tokens: set[str], paths: set[Path]) -> None:
        if isinstance(value, dict):
            serialized = json.dumps(value, ensure_ascii=False)
            if any(token in serialized for token in tokens if len(token) >= 8):
                self._collect_paths(value, paths)
            for child in value.values():
                self._collect_matching_objects(child, tokens, paths)
        elif isinstance(value, list):
            for child in value:
                self._collect_matching_objects(child, tokens, paths)

    def _collect_paths(self, value: Any, paths: set[Path]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and (key.endswith("_path") or key in {"path", "local_result_directory"}):
                    candidate = Path(child)
                    if candidate.is_dir():
                        paths.update(item for item in candidate.iterdir() if item.is_file())
                    else:
                        paths.add(candidate)
                else:
                    self._collect_paths(child, paths)
        elif isinstance(value, list):
            for child in value:
                self._collect_paths(child, paths)

    @staticmethod
    def _identity_tokens(value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and (key.endswith("_id") or key in {"task_id", "job_id"}):
                    found.add(child)
                else:
                    found.update(ResearchAssetService._identity_tokens(child))
        elif isinstance(value, list):
            for child in value:
                found.update(ResearchAssetService._identity_tokens(child))
        return found

    def _resolve_file(self, task_id: str, file_id: str) -> Path:
        for path in self._task_paths(task_id, self._task(task_id)):
            if self._file_id(path) == file_id:
                return path
        raise FileNotFoundError("Task artifact not found.")

    def _describe(self, path: Path) -> dict[str, Any]:
        label = path.parent.name if path.name in STRUCTURE_NAMES else path.stem
        return {
            "file_id": self._file_id(path),
            "name": path.name,
            "label": label,
            "suffix": path.suffix.lower(),
            "category": self._category(path),
            "size_bytes": path.stat().st_size,
            "previewable": path.name in PREVIEW_NAMES or path.suffix.lower() in {".vasp", ".cif", ".json", ".txt", ".out"},
            "downloadable": path.name != "POTCAR",
            "structure": path.name in STRUCTURE_NAMES or path.suffix.lower() in {".vasp", ".cif"},
        }

    @staticmethod
    def _category(path: Path) -> str:
        text = str(path).lower()
        if "cluster_results" in text:
            return "DFT 结果"
        if "adsorption" in text:
            return "吸附计算"
        if "screening_and_slabs" in text:
            return "slab 结构"
        if "dft_" in text or path.name in {"INCAR", "KPOINTS", "POTCAR", "vasp.slurm"}:
            return "DFT 输入"
        return "结构与报告"

    @staticmethod
    def _file_id(path: Path) -> str:
        relative = path.resolve().relative_to(DATA_ROOT).as_posix()
        return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _inside_data(path: Path) -> bool:
        try:
            path.resolve().relative_to(DATA_ROOT)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _potcar_labels(path: Path) -> list[str]:
        labels = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "TITEL" in line:
                labels.append(line.split("=", 1)[-1].strip())
        return labels

    @staticmethod
    def _parse_poscar(path: Path) -> dict[str, Any]:
        lines = [line.rstrip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
        if len(lines) < 8:
            raise ValueError("POSCAR is incomplete.")
        scale = float(lines[1].split()[0])
        lattice = [[float(value) * scale for value in lines[index].split()[:3]] for index in range(2, 5)]
        symbols = lines[5].split()
        counts = [int(value) for value in lines[6].split()]
        cursor = 7
        selective = lines[cursor].strip().lower().startswith("s")
        if selective:
            cursor += 1
        direct = lines[cursor].strip().lower().startswith(("d", "f"))
        cursor += 1
        atoms = []
        expanded = [symbol for symbol, count in zip(symbols, counts) for _ in range(count)]
        for index, symbol in enumerate(expanded):
            parts = lines[cursor + index].split()
            raw = [float(value) for value in parts[:3]]
            position = [sum(raw[j] * lattice[j][axis] for j in range(3)) for axis in range(3)] if direct else [value * scale for value in raw]
            flags = parts[3:6] if selective else ["T", "T", "T"]
            atoms.append({
                "index": index + 1,
                "element": symbol,
                "position": position,
                "movable": all(flag.upper().startswith("T") for flag in flags),
            })
        return {"lattice": lattice, "atoms": atoms, "atom_count": len(atoms), "elements": symbols}

    @staticmethod
    def _parse_cif(path: Path) -> dict[str, Any]:
        try:
            from ase.io import read
        except ImportError as error:
            raise RuntimeError("ASE is required to preview CIF structures.") from error
        structure = read(str(path), format="cif")
        lattice = [[float(value) for value in row] for row in structure.cell.array]
        symbols = list(structure.get_chemical_symbols())
        atoms = [
            {
                "index": index + 1,
                "element": symbol,
                "position": [float(value) for value in position],
                "movable": True,
            }
            for index, (symbol, position) in enumerate(zip(symbols, structure.positions))
        ]
        return {
            "lattice": lattice,
            "atoms": atoms,
            "atom_count": len(atoms),
            "elements": list(dict.fromkeys(symbols)),
        }
