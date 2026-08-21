from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Sequence


class OvitoService:
    """Open generated POSCAR files in the locally installed OVITO GUI."""

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
        self.executable = self._find_executable()

    def open_structures(self, poscar_paths: Sequence[str | Path]) -> dict[str, object]:
        requested_paths = [Path(path).resolve() for path in poscar_paths if path]
        paths = requested_paths[:1]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"OVITO 待加载结构不存在: {', '.join(missing)}")
        if not paths:
            return {"opened": False, "files": [], "reason": "没有 POSCAR 文件。"}
        if not self.executable:
            raise FileNotFoundError(
                "没有找到 OVITO。请把 ovito.exe 的完整路径写入项目根目录 .ovito-path。"
            )

        subprocess.Popen(
            [str(self.executable), *[str(path) for path in paths]],
            cwd=self.executable.parent,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return {
            "opened": True,
            "executable": str(self.executable),
            "files": [str(path) for path in paths],
            "requested_count": len(requested_paths),
            "opened_count": len(paths),
            "truncated": len(requested_paths) > 1,
        }

    def _find_executable(self) -> Path | None:
        configured = self.project_root / ".ovito-path"
        candidates = []
        if configured.is_file():
            candidates.append(Path(configured.read_text(encoding="utf-8").strip()))
        env_path = os.environ.get("OVITO_PATH")
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend(
            [
                Path.home() / "Desktop" / "OVITO Basic" / "ovito.exe",
                Path("C:/Program Files/OVITO Basic/ovito.exe"),
                Path("C:/Program Files/OVITO Pro/ovito.exe"),
            ]
        )
        return next((path.resolve() for path in candidates if path.is_file()), None)
