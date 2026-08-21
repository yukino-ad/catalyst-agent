from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PYTHON = {(3, 10), (3, 11)}
REQUIRED_IMPORTS = {
    "dotenv": "python-dotenv",
    "langgraph": "langgraph",
    "numpy": "numpy",
    "ase": "ase",
    "pymatgen": "pymatgen",
    "sklearn": "scikit-learn",
    "torch": "torch",
}


def inspect_environment() -> dict[str, Any]:
    env_values = _read_env_values(PROJECT_ROOT / ".env")
    version = (sys.version_info.major, sys.version_info.minor)
    imports = {}
    for module, distribution in REQUIRED_IMPORTS.items():
        available = importlib.util.find_spec(module) is not None
        package_version = None
        if available:
            try:
                package_version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                package_version = "unknown"
        imports[module] = {
            "available": available,
            "distribution": distribution,
            "version": package_version,
        }

    executable = Path(sys.executable).resolve()
    environment_root = executable.parent.parent
    inside_project_venv = (
        PROJECT_ROOT == environment_root.parent
        and environment_root.name.startswith(".venv")
    )
    safety = {
        "CLUSTER_PREFLIGHT_ENABLED": _setting(
            env_values, "CLUSTER_PREFLIGHT_ENABLED", "false"
        ),
        "CLUSTER_REMOTE_WRITE_ENABLED": _setting(
            env_values, "CLUSTER_REMOTE_WRITE_ENABLED", "false"
        ),
        "CLUSTER_SUBMISSION_ENABLED": _setting(
            env_values, "CLUSTER_SUBMISSION_ENABLED", "false"
        ),
    }
    missing = [name for name, item in imports.items() if not item["available"]]
    safe_cluster = (
        safety["CLUSTER_REMOTE_WRITE_ENABLED"] == "false"
        and safety["CLUSTER_SUBMISSION_ENABLED"] == "false"
    )
    checks = {
        "supported_python": version in SUPPORTED_PYTHON,
        "inside_project_venv": inside_project_venv,
        "dependencies_available": not missing,
        "cluster_safe_by_default": safe_cluster,
        "requirements_present": (PROJECT_ROOT / "requirements.txt").is_file(),
    }
    return {
        "schema_version": "environment-check-v1",
        "status": "environment_ready" if all(checks.values()) else "environment_not_ready",
        "project_root": str(PROJECT_ROOT),
        "python": {
            "executable": str(executable),
            "version": platform.python_version(),
            "supported_versions": ["3.10", "3.11"],
        },
        "checks": checks,
        "missing_imports": missing,
        "dependencies": imports,
        "cluster_safety": safety,
    }


def _read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _setting(values: dict[str, str], key: str, default: str) -> str:
    return os.getenv(key, values.get(key, default)).strip().lower()


def main() -> None:
    result = inspect_environment()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "environment_ready" else 1)


if __name__ == "__main__":
    main()
