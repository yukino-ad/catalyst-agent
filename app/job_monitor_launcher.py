from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SESSION_ROOT = Path("data/cluster_monitor/sessions")


def _enabled() -> bool:
    raw = os.getenv("JOB_MONITOR_AUTO_OPEN", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _running(pid: int) -> bool:
    if pid <= 0 or os.name != "nt":
        return False
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            and code.value == 259
        )
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def launch_job_monitor(result: dict[str, Any]) -> dict[str, Any]:
    recording = result.get("submission_recording", {})
    if recording.get("status") != "submission_jobs_recorded":
        return {"status": "monitor_not_requested", "reason": "no_recorded_submission"}
    job_ids = [
        str(row.get("slurm_job_id", ""))
        for row in recording.get("records", [])
        if str(row.get("slurm_job_id", "")).isdigit()
    ]
    task_id = str(recording.get("task_id") or result.get("task_id") or "").strip()
    if not job_ids or not task_id:
        return {"status": "monitor_not_requested", "reason": "missing_identity"}
    if os.name != "nt" or not sys.stdin.isatty() or not _enabled():
        return {"status": "monitor_not_requested", "reason": "auto_open_disabled"}

    SESSION_ROOT.mkdir(parents=True, exist_ok=True)
    session_path = SESSION_ROOT / f"{job_ids[0]}.json"
    try:
        previous = json.loads(session_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        previous = {}
    if _running(int(previous.get("monitor_pid", 0) or 0)):
        return {
            "status": "monitor_already_running",
            "monitor_pid": previous["monitor_pid"],
            "session_path": str(session_path.resolve()),
        }

    interval = max(15, int(os.getenv("JOB_MONITOR_INTERVAL_SECONDS", "60")))
    python = str(Path(sys.executable).resolve()).replace("'", "''")
    working = str(Path.cwd().resolve()).replace("'", "''")
    arguments = " ".join(job_ids)
    command = (
        f"Set-Location -LiteralPath '{working}'; "
        "$env:PYTHONIOENCODING='utf-8'; "
        f"& '{python}' -u -m app.job_status_watch_cli "
        f"--task-id '{task_id}' --job-ids {arguments} --interval {interval}"
    )
    process = subprocess.Popen(
        ["powershell.exe", "-NoExit", "-NoProfile", "-Command", command],
        cwd=Path.cwd(),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    session = {
        "schema_version": "job-monitor-session-v1",
        "task_id": task_id,
        "slurm_job_ids": job_ids,
        "monitor_pid": process.pid,
        "status": "running",
        "launched_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = session_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(session_path)
    return {
        "status": "monitor_launched",
        "monitor_pid": process.pid,
        "session_path": str(session_path.resolve()),
        "slurm_job_ids": job_ids,
    }
