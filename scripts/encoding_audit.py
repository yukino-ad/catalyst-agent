"""Audit repository text for UTF-8, JSON, and common mojibake damage."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_ROOTS = (
    "app",
    "tools",
    "configs",
    "prompts",
    "scripts",
    "tests",
    "docs",
    "data",
)
TEXT_SUFFIXES = {
    ".py",
    ".json",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
}
UNICODE_RUN = re.compile(r"[^\x00-\x7f]{2,}")
CJK = re.compile(r"[\u3400-\u9fff]")
EXCLUDED_RELATIVE_ROOTS = (
    Path("data/edge-qa-selection"),
)


def audit(root: Path) -> dict[str, Any]:
    files = []
    errors = []

    for relative_root in DEFAULT_ROOTS:
        directory = root / relative_root
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            relative_path = path.relative_to(root)
            if any(
                relative_path.is_relative_to(excluded)
                for excluded in EXCLUDED_RELATIVE_ROOTS
            ):
                continue
            files.append(path)
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except UnicodeError as error:
                errors.append(_error(path, root, "invalid_utf8", str(error)))
                continue

            if "\ufffd" in text:
                errors.append(
                    _error(path, root, "replacement_character", "Contains U+FFFD")
                )
            if path.suffix.lower() == ".json":
                try:
                    json.loads(text.lstrip("\ufeff"))
                except json.JSONDecodeError as error:
                    errors.append(_error(path, root, "invalid_json", str(error)))

            for match in UNICODE_RUN.finditer(text):
                restored = _restore_mojibake(match.group(0))
                if restored is not None:
                    errors.append(
                        _error(
                            path,
                            root,
                            "reversible_gbk_utf8_mojibake",
                            f"{match.group(0)!r} may be {restored!r}",
                        )
                    )
                    break

    return {
        "status": "encoding_audit_passed" if not errors else "encoding_audit_failed",
        "scanned_file_count": len(files),
        "error_count": len(errors),
        "errors": errors,
    }


def _restore_mojibake(value: str) -> str | None:
    try:
        restored = value.encode("gbk").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if restored == value or not CJK.search(restored):
        return None
    return restored


def _error(path: Path, root: Path, kind: str, message: str) -> dict[str, str]:
    return {
        "path": str(path.relative_to(root)),
        "kind": kind,
        "message": message,
    }


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")

    parser = argparse.ArgumentParser(description="Audit Catalyst Agent text encoding")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    result = audit(Path(args.root).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not result["errors"] else 1)


if __name__ == "__main__":
    main()
