"""Process-wide UTF-8 safeguards for Windows and Unix CLI execution."""

from __future__ import annotations

import os
import sys


def configure_utf8_stdio() -> None:
    """Make CLI text deterministic without changing persisted data."""

    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="strict")
        except (AttributeError, OSError, ValueError):
            # Embedded runners and redirected streams may reject reconfigure.
            continue
