from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from app.domain.cluster_transport import ClusterTransport
from app.domain.remote_upload import RemoteUploadSettings
from app.domain.slurm_monitor import SlurmMonitorService
from app.domain.submitted_job_repository import SubmittedJobRepository
from app.domain.vasp_completion import VaspCompletionService


TERMINAL_STATES = {
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL",
    "OUT_OF_MEMORY", "PREEMPTED", "BOOT_FAIL", "DEADLINE", "REVOKED",
}


class JobStatusConsole:
    def __init__(self, task_id: str, job_ids: list[str], interval: int = 60) -> None:
        if not task_id or any(not value.isdigit() for value in job_ids):
            raise ValueError("A task ID and numeric Slurm job IDs are required")
        self.task_id = task_id
        self.job_ids = list(dict.fromkeys(job_ids))
        self.interval = max(15, interval)
        self.repository = SubmittedJobRepository()
        self.transport = ClusterTransport()
        self.monitor = SlurmMonitorService(
            repository=self.repository, transport=self.transport
        )
        self.completion = VaspCompletionService(
            repository=self.repository, transport=self.transport
        )

    def status(self) -> list[dict[str, Any]]:
        result = self.monitor.poll(self.job_ids)
        rows = result.get("jobs", [])
        terminal = [
            str(row["slurm_job_id"])
            for row in rows
            if row.get("scheduler_state") in TERMINAL_STATES
        ]
        completion = {}
        if terminal:
            checked = self.completion.inspect(terminal)
            completion = {
                str(row["slurm_job_id"]): row
                for row in checked.get("jobs", [])
            }
        final = [completion.get(str(row["slurm_job_id"]), row) for row in rows]
        self._print_rows(final, result.get("errors", []))
        return final

    def details(self) -> None:
        for job_id in self.job_ids:
            output = self.transport.run(
                f"sacct -n -X -j {job_id} "
                "--format=JobID,JobName,Partition,State,Elapsed,ExitCode,NodeList -P"
            )
            print(f"\n[{job_id}] sacct\n{output or 'No sacct record found'}")

    def files(self) -> None:
        root = RemoteUploadSettings.from_environment().remote_runs_root
        for job_id in self.job_ids:
            record = self.repository.get(job_id)
            if not record:
                print(f"[{job_id}] persisted record not found")
                continue
            directory = self.transport.validate_remote_child(
                str(record["remote_job_directory"]), root
            )
            quoted = self.transport.quote(directory)
            output = self.transport.run(
                f"find {quoted} -maxdepth 1 -type f -printf '%f|%s bytes|%TY-%Tm-%Td %TH:%TM\\n' | sort"
            )
            print(f"\n[{job_id}] remote files\n{output or 'No files found'}")

    def download(self) -> None:
        subprocess.run(
            [sys.executable, "-u", "-m", "app.cluster_jobs_cli", "poll", *self.job_ids],
            check=False,
        )

    def watch(self) -> None:
        print(f"Watching every {self.interval} seconds. Press Ctrl+C to stop watching.")
        try:
            while True:
                rows = self.status()
                if rows and all(row.get("scheduler_state") in TERMINAL_STATES for row in rows):
                    print("All selected jobs reached a terminal scheduler state.")
                    return
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\nAutomatic refresh stopped.")

    def run(self) -> None:
        print("\nCatalyst Agent Job Monitor")
        print(f"Task ID: {self.task_id}")
        print(f"Slurm Job IDs: {', '.join(self.job_ids)}")
        print("Commands: status, watch, details, files, download, help, exit")
        self.status()
        while True:
            command = input("\nmonitor> ").strip().lower()
            try:
                if command in {"", "status", "s"}:
                    self.status()
                elif command in {"watch", "w"}:
                    self.watch()
                elif command in {"details", "d"}:
                    self.details()
                elif command in {"files", "f"}:
                    self.files()
                elif command == "download":
                    self.download()
                elif command in {"help", "h", "?"}:
                    print("status: query squeue/sacct; watch: auto-refresh; details: sacct details")
                    print("files: list remote files; download: enter the existing human download flow")
                elif command in {"exit", "quit", "q", "stop"}:
                    return
                else:
                    print("Unknown command. Enter help for available commands.")
            except Exception as error:
                print(f"Command failed: {type(error).__name__}: {error}")

    @staticmethod
    def _print_rows(rows: list[dict[str, Any]], errors: list[dict[str, Any]]) -> None:
        if not rows:
            print("No persisted jobs matched the requested IDs.")
        for row in rows:
            print(
                f"[{row.get('slurm_job_id')}] "
                f"state={row.get('scheduler_state', 'UNKNOWN')} "
                f"elapsed={row.get('scheduler_elapsed') or '-'} "
                f"vasp={row.get('vasp_decision') or 'not_checked'} "
                f"detail={row.get('scheduler_detail') or '-'}"
            )
        for error in errors:
            print(f"[{error.get('slurm_job_id')}] ERROR: {error.get('message')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Slurm/VASP job monitor")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--job-ids", nargs="+", required=True)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    JobStatusConsole(args.task_id, args.job_ids, args.interval).run()


if __name__ == "__main__":
    main()
