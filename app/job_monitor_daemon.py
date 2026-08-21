from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.slurm_monitor import SlurmMonitorService
from app.domain.submitted_job_repository import SubmittedJobRepository
from app.domain.vasp_completion import VaspCompletionService


ROOT = Path("data/cluster_monitor")
PID_PATH = ROOT / "monitor.pid"
STOP_PATH = ROOT / "monitor.stop"
STATE_PATH = ROOT / "state.json"
EVENT_PATH = ROOT / "events.jsonl"
LOG_PATH = ROOT / "monitor.log"

TERMINAL_STATES = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "BOOT_FAIL",
    "DEADLINE",
    "REVOKED",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_event(value: dict[str, Any]) -> None:
    EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def _is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(
                kernel32.GetExitCodeProcess(
                    handle,
                    ctypes.byref(exit_code),
                )
                and exit_code.value == still_active
            )
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _current_pid() -> int | None:
    try:
        pid = int(PID_PATH.read_text(encoding="ascii").strip())
    except (FileNotFoundError, ValueError, OSError):
        return None
    return pid if _is_running(pid) else None


def _windows_notification(title: str, message: str) -> None:
    if os.name != "nt":
        return
    safe_title = title.replace("'", "''")
    safe_message = message.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;"
        f"$n.BalloonTipTitle='{safe_title}';"
        f"$n.BalloonTipText='{safe_message}';"
        "$n.Visible=$true;$n.ShowBalloonTip(8000);"
        "Start-Sleep -Seconds 9;$n.Dispose()"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-Command", script],
        creationflags=creation_flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _notify(event: dict[str, Any]) -> None:
    job_id = str(event["slurm_job_id"])
    state = str(event["scheduler_state"])
    decision = str(event.get("vasp_decision", ""))
    if decision == "completed_converged":
        detail = f"Job {job_id} converged. Run: python -u -m app.cluster_jobs_cli poll {job_id}"
    elif state in TERMINAL_STATES:
        detail = f"Job {job_id} reached {state}. Open the monitor log for diagnosis."
    else:
        detail = f"Job {job_id}: {state}"
    print(f"[{_now()}] {detail}", flush=True)
    _windows_notification("Catalyst Agent DFT", detail)


def poll_once(
    job_ids: list[str] | None = None,
    repository: SubmittedJobRepository | None = None,
    monitor: SlurmMonitorService | None = None,
    completion: VaspCompletionService | None = None,
) -> dict[str, Any]:
    repository = repository or SubmittedJobRepository()
    monitor = monitor or SlurmMonitorService(repository=repository)
    completion = completion or VaspCompletionService(repository=repository)
    previous = _read_json(STATE_PATH, {})
    records = repository.list_records()
    wanted = set(job_ids or [])
    candidates = [
        str(record["slurm_job_id"])
        for record in records
        if (
            (not wanted or str(record.get("slurm_job_id")) in wanted)
            and str(record.get("scheduler_state", "")) not in TERMINAL_STATES
        )
    ]
    # A completed scheduler record may still need a one-time VASP notification.
    candidates.extend(
        str(record["slurm_job_id"])
        for record in records
        if (
            (not wanted or str(record.get("slurm_job_id")) in wanted)
            and str(record.get("slurm_job_id")) not in previous
            and record.get("download_status") != "downloaded"
        )
    )
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return {"status": "monitor_idle", "polled_count": 0, "events": []}

    monitor_result = monitor.poll(candidates)
    terminal_ids = [
        str(job["slurm_job_id"])
        for job in monitor_result.get("jobs", [])
        if job.get("scheduler_state") in TERMINAL_STATES
    ]
    completion_jobs: dict[str, dict[str, Any]] = {}
    if terminal_ids:
        checked = completion.inspect(terminal_ids)
        completion_jobs = {
            str(job["slurm_job_id"]): job
            for job in checked.get("jobs", [])
        }

    current = dict(previous)
    events: list[dict[str, Any]] = []
    for job in monitor_result.get("jobs", []):
        job_id = str(job["slurm_job_id"])
        resolved = completion_jobs.get(job_id, job)
        snapshot = {
            "scheduler_state": resolved.get("scheduler_state", "UNKNOWN"),
            "vasp_decision": resolved.get("vasp_decision", ""),
        }
        if previous.get(job_id) != snapshot:
            event = {
                "timestamp": _now(),
                "slurm_job_id": job_id,
                "task_id": resolved.get("task_id", ""),
                "job_id": resolved.get("job_id", ""),
                **snapshot,
            }
            events.append(event)
            _append_event(event)
            _notify(event)
        current[job_id] = snapshot
    _atomic_json(STATE_PATH, current)
    return {
        "status": "monitor_polled",
        "polled_count": len(monitor_result.get("jobs", [])),
        "failed_count": len(monitor_result.get("errors", [])),
        "events": events,
        "errors": monitor_result.get("errors", []),
    }


def run(interval_seconds: int, job_ids: list[str]) -> None:
    if interval_seconds < 15:
        raise ValueError("interval must be at least 15 seconds")
    ROOT.mkdir(parents=True, exist_ok=True)
    STOP_PATH.unlink(missing_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="ascii")
    print(
        f"DFT monitor started, pid={os.getpid()}, interval={interval_seconds}s",
        flush=True,
    )
    try:
        while not STOP_PATH.exists():
            try:
                result = poll_once(job_ids or None)
                print(json.dumps(result, ensure_ascii=False), flush=True)
            except Exception as error:
                print(
                    f"[{_now()}] monitor error: {type(error).__name__}: {error}",
                    flush=True,
                )
            for _ in range(interval_seconds):
                if STOP_PATH.exists():
                    break
                time.sleep(1)
    finally:
        PID_PATH.unlink(missing_ok=True)
        STOP_PATH.unlink(missing_ok=True)
        print("DFT monitor stopped", flush=True)


def start(interval_seconds: int, job_ids: list[str]) -> int:
    running = _current_pid()
    if running is not None:
        raise RuntimeError(f"DFT monitor is already running with pid {running}")
    ROOT.mkdir(parents=True, exist_ok=True)
    STOP_PATH.unlink(missing_ok=True)
    command = [
        sys.executable,
        "-u",
        "-m",
        "app.job_monitor_daemon",
        "run",
        "--interval",
        str(interval_seconds),
    ]
    if job_ids:
        command.extend(["--job-ids", *job_ids])
    creation_flags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    log = LOG_PATH.open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=Path.cwd(),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
        close_fds=True,
    )
    log.close()
    PID_PATH.write_text(str(process.pid), encoding="ascii")
    return process.pid


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Background Slurm monitor with local state-change notifications."
    )
    parser.add_argument("action", choices=["start", "run", "once", "status", "stop"])
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--job-ids", nargs="*", default=[])
    args = parser.parse_args()
    if any(not value.isdigit() for value in args.job_ids):
        raise ValueError("Every Slurm job ID must contain digits only")

    if args.action == "start":
        pid = start(args.interval, args.job_ids)
        print(f"DFT monitor started in background, pid={pid}")
        print(f"Log: {LOG_PATH.resolve()}")
    elif args.action == "run":
        run(args.interval, args.job_ids)
    elif args.action == "once":
        print(json.dumps(poll_once(args.job_ids or None), ensure_ascii=False, indent=2))
    elif args.action == "status":
        pid = _current_pid()
        print(json.dumps({
            "running": pid is not None,
            "pid": pid,
            "log_path": str(LOG_PATH.resolve()),
            "event_path": str(EVENT_PATH.resolve()),
        }, ensure_ascii=False, indent=2))
    else:
        pid = _current_pid()
        if pid is None:
            print("DFT monitor is not running")
        else:
            ROOT.mkdir(parents=True, exist_ok=True)
            STOP_PATH.write_text(_now(), encoding="ascii")
            print(f"Stop requested for DFT monitor pid={pid}")


if __name__ == "__main__":
    main()
