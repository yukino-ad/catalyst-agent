from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Sequence


class PostprocessService:
    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
        self.python = Path((self.project_root / ".cgcnn-python").read_text(encoding="utf-8").strip())
        self.site_packages = self.project_root / "models" / "cgcnn-master" / "venv" / "Lib" / "site-packages"
        self.helper = self.project_root / "app" / "legacy" / "material_postprocess.py"
        self.output_dir = self.project_root / "data" / "screening_and_slabs"

    def screen_and_cleave(
        self,
        cif_paths: Sequence[str | Path],
        poscar_paths: Sequence[str | Path],
    ) -> dict:
        cifs = [Path(path).resolve() for path in cif_paths]
        poscars = [Path(path).resolve() for path in poscar_paths]
        if len(cifs) != len(poscars):
            raise ValueError("CIF 和 POSCAR 数量必须一致。")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        screening_json = self.output_dir / "latest_screening.json"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.site_packages) + os.pathsep + env.get("PYTHONPATH", "")
        command = [
            str(self.python), str(self.helper),
            "--cif", *map(str, cifs),
            "--poscar", *map(str, poscars),
            "--output", str(self.output_dir),
            "--screening-json", str(screening_json),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if completed.returncode:
            raise RuntimeError(f"稳定性判据或 111 切面失败:\n{completed.stdout}\n{completed.stderr}")
        return json.loads(screening_json.read_text(encoding="utf-8"))
