from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class ClusterReadonlySettings:
    enabled: bool
    host: str
    port: int
    user: str
    key_path: Path
    known_hosts_path: Path
    timeout_seconds: int
    remote_root: str
    slurm_partition: str
    vasp_module: str
    vasp_executable: str
    vasp_command: str

    @classmethod
    def from_environment(
        cls,
    ) -> "ClusterReadonlySettings":
        enabled = os.getenv(
            "CLUSTER_PREFLIGHT_ENABLED",
            "false",
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        return cls(
            enabled=enabled,
            host=os.getenv(
                "CLUSTER_SSH_HOST",
                "",
            ).strip(),
            port=int(
                os.getenv(
                    "CLUSTER_SSH_PORT",
                    "22",
                )
            ),
            user=os.getenv(
                "CLUSTER_SSH_USER",
                "",
            ).strip(),
            key_path=Path(
                os.getenv(
                    "CLUSTER_SSH_KEY_PATH",
                    "",
                )
            ).expanduser(),
            known_hosts_path=Path(
                os.getenv(
                    "CLUSTER_SSH_KNOWN_HOSTS",
                    "",
                )
            ).expanduser(),
            timeout_seconds=int(
                os.getenv(
                    "CLUSTER_CONNECT_TIMEOUT_SECONDS",
                    "20",
                )
            ),
            remote_root=os.getenv(
                "CLUSTER_REMOTE_ROOT",
                "",
            ).strip(),
            slurm_partition=os.getenv(
                "CLUSTER_SLURM_PARTITION",
                "",
            ).strip(),
            vasp_module=os.getenv(
                "CLUSTER_VASP_MODULE",
                "",
            ).strip(),
            vasp_executable=os.getenv(
                "CLUSTER_VASP_EXECUTABLE",
                "vasp_std",
            ).strip(),
            vasp_command=os.getenv(
                "CLUSTER_VASP_COMMAND",
                "",
            ).strip(),
        )


class ClusterReadonlyPreflightService:
    """Inspect remote HPC resources without writing or submitting."""

    SAFE_HOST = re.compile(
        r"^[A-Za-z0-9.-]+$"
    )
    SAFE_USER = re.compile(
        r"^[A-Za-z0-9._-]+$"
    )
    SAFE_NAME = re.compile(
        r"^[A-Za-z0-9._/+:-]+$"
    )
    SAFE_REMOTE_PATH = re.compile(
        r"^/[A-Za-z0-9._/+:-]+$"
    )

    def __init__(
        self,
        settings: ClusterReadonlySettings | None = None,
    ) -> None:
        self.settings = (
            settings
            or ClusterReadonlySettings.from_environment()
        )

    def inspect(
        self,
        jobs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(jobs, list):
            raise TypeError("jobs must be a list")

        if not jobs:
            return self._result(
                status=(
                    "cluster_readonly_preflight_skipped"
                ),
                jobs=[],
                checks=[],
                errors=[],
            )

        if not self.settings.enabled:
            return self._result(
                status=(
                    "cluster_readonly_preflight_disabled"
                ),
                jobs=jobs,
                checks=[],
                errors=[{
                    "check": "cluster_preflight_enabled",
                    "message": (
                        "CLUSTER_PREFLIGHT_ENABLED "
                        "is false"
                    ),
                }],
            )

        checks: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        ssh_executable = shutil.which("ssh")

        self._check(
            checks,
            errors,
            "local_ssh_available",
            bool(ssh_executable),
            "Windows OpenSSH client was not found",
        )

        self._check(
            checks,
            errors,
            "ssh_host_valid",
            bool(
                self.SAFE_HOST.fullmatch(
                    self.settings.host
                )
            ),
            "CLUSTER_SSH_HOST is missing or invalid",
        )

        self._check(
            checks,
            errors,
            "ssh_user_valid",
            bool(
                self.SAFE_USER.fullmatch(
                    self.settings.user
                )
            ),
            "CLUSTER_SSH_USER is missing or invalid",
        )

        self._check(
            checks,
            errors,
            "ssh_port_valid",
            1 <= self.settings.port <= 65535,
            "CLUSTER_SSH_PORT is invalid",
        )

        self._check(
            checks,
            errors,
            "ssh_key_exists",
            self.settings.key_path.is_file(),
            (
                "SSH private key does not exist: "
                f"{self.settings.key_path}"
            ),
        )

        self._check(
            checks,
            errors,
            "known_hosts_exists",
            self.settings.known_hosts_path.is_file(),
            (
                "known_hosts does not exist: "
                f"{self.settings.known_hosts_path}"
            ),
        )

        self._check(
            checks,
            errors,
            "timeout_valid",
            1 <= self.settings.timeout_seconds <= 120,
            (
                "CLUSTER_CONNECT_TIMEOUT_SECONDS "
                "must be between 1 and 120"
            ),
        )

        self._check(
            checks,
            errors,
            "remote_root_valid",
            bool(
                self.SAFE_REMOTE_PATH.fullmatch(
                    self.settings.remote_root
                )
            ),
            (
                "CLUSTER_REMOTE_ROOT must be an "
                "absolute Unix path"
            ),
        )

        self._check(
            checks,
            errors,
            "partition_valid",
            bool(
                self.SAFE_NAME.fullmatch(
                    self.settings.slurm_partition
                )
            ),
            "CLUSTER_SLURM_PARTITION is invalid",
        )

        self._check(
            checks,
            errors,
            "vasp_module_valid",
            bool(
                self.SAFE_NAME.fullmatch(
                    self.settings.vasp_module
                )
            ),
            "CLUSTER_VASP_MODULE is invalid",
        )

        self._check(
            checks,
            errors,
            "vasp_executable_valid",
            bool(
                self.SAFE_NAME.fullmatch(
                    self.settings.vasp_executable
                )
            ),
            "CLUSTER_VASP_EXECUTABLE is invalid",
        )

        if errors:
            return self._result(
                status=(
                    "cluster_readonly_preflight_failed"
                ),
                jobs=jobs,
                checks=checks,
                errors=errors,
            )

        command = self._ssh_command(
            ssh_executable=str(ssh_executable),
        )

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            errors.append({
                "check": "ssh_connection",
                "message": (
                    "SSH read-only preflight timed out"
                ),
            })
            return self._result(
                status=(
                    "cluster_readonly_preflight_failed"
                ),
                jobs=jobs,
                checks=checks,
                errors=errors,
            )
        except OSError as error:
            errors.append({
                "check": "ssh_connection",
                "message": str(error),
            })
            return self._result(
                status=(
                    "cluster_readonly_preflight_failed"
                ),
                jobs=jobs,
                checks=checks,
                errors=errors,
            )

        markers = self._parse_markers(
            completed.stdout
        )

        self._check(
            checks,
            errors,
            "ssh_connection",
            (
                completed.returncode == 0
                and markers.get("connection") == "ok"
            ),
            (
                "SSH connection failed: "
                f"{completed.stderr.strip()[:500]}"
            ),
        )

        self._check_marker(
            checks,
            errors,
            markers,
            "remote_root",
            "Remote working root is unavailable",
        )
        self._check_marker(
            checks,
            errors,
            markers,
            "sbatch",
            "sbatch is unavailable",
        )
        self._check_marker(
            checks,
            errors,
            markers,
            "squeue",
            "squeue is unavailable",
        )
        self._check_marker(
            checks,
            errors,
            markers,
            "sinfo",
            "sinfo is unavailable",
        )
        self._check_marker(
            checks,
            errors,
            markers,
            "partition",
            "Configured Slurm partition is unavailable",
        )
        self._check_marker(
            checks,
            errors,
            markers,
            "module",
            "Configured VASP module could not be loaded",
        )
        self._check_marker(
            checks,
            errors,
            markers,
            "vasp_executable",
            "VASP executable is unavailable after module load",
        )

        status = (
            "cluster_readonly_preflight_passed"
            if not errors
            else "cluster_readonly_preflight_failed"
        )

        return self._result(
            status=status,
            jobs=jobs,
            checks=checks,
            errors=errors,
            remote_hostname=markers.get(
                "hostname",
                "",
            ),
        )

    def _ssh_command(
        self,
        ssh_executable: str,
    ) -> list[str]:
        destination = (
            f"{self.settings.user}@"
            f"{self.settings.host}"
        )

        return [
            ssh_executable,
            "-T",
            "-p",
            str(self.settings.port),
            "-i",
            str(self.settings.key_path.resolve()),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            (
                "UserKnownHostsFile="
                f"{self.settings.known_hosts_path.resolve()}"
            ),
            "-o",
            (
                "ConnectTimeout="
                f"{self.settings.timeout_seconds}"
            ),
            destination,
            self._remote_probe(),
        ]

    def _remote_probe(self) -> str:
        root = shlex.quote(
            self.settings.remote_root
        )
        partition = shlex.quote(
            self.settings.slurm_partition
        )
        module_name = shlex.quote(
            self.settings.vasp_module
        )
        executable = shlex.quote(
            self.settings.vasp_executable
        )

        probe = "; ".join([
            "printf 'connection=ok\\n'",
            (
                "printf 'hostname=%s\\n' "
                "\"$(hostname 2>/dev/null)\""
            ),
            (
                f"if test -d {root} "
                f"&& test -r {root}; "
                "then printf 'remote_root=ok\\n'; "
                "else printf 'remote_root=missing\\n'; fi"
            ),
            self._command_probe("sbatch"),
            self._command_probe("squeue"),
            self._command_probe("sinfo"),
            (
                "if command -v sinfo >/dev/null 2>&1 "
                f"&& sinfo -h -p {partition} "
                "-o '%P' 2>/dev/null | grep -q .; "
                "then printf 'partition=ok\\n'; "
                "else printf 'partition=missing\\n'; fi"
            ),
            (
                "source /etc/profile >/dev/null 2>&1 "
                "|| true"
            ),
            (
                f"if module load {module_name} "
                ">/dev/null 2>&1; "
                "then printf 'module=ok\\n'; "
                "else printf 'module=missing\\n'; fi"
            ),
            (
                f"if command -v {executable} "
                ">/dev/null 2>&1; "
                "then printf 'vasp_executable=ok\\n'; "
                "else printf "
                "'vasp_executable=missing\\n'; fi"
            ),
        ])

        return f"bash -lc {shlex.quote(probe)}"

    @staticmethod
    def _command_probe(
        command: str,
    ) -> str:
        return (
            f"if command -v {command} "
            ">/dev/null 2>&1; "
            f"then printf '{command}=ok\\n'; "
            f"else printf '{command}=missing\\n'; fi"
        )

    @staticmethod
    def _parse_markers(
        output: str,
    ) -> dict[str, str]:
        markers: dict[str, str] = {}

        for line in output.splitlines():
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            markers[key.strip()] = value.strip()

        return markers

    @staticmethod
    def _check_marker(
        checks: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        markers: dict[str, str],
        name: str,
        message: str,
    ) -> None:
        ClusterReadonlyPreflightService._check(
            checks,
            errors,
            name,
            markers.get(name) == "ok",
            message,
        )

    @staticmethod
    def _check(
        checks: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        name: str,
        passed: bool,
        message: str,
    ) -> None:
        checks.append({
            "name": name,
            "passed": bool(passed),
        })

        if not passed:
            errors.append({
                "check": name,
                "message": message,
            })

    @staticmethod
    def _mask_user(
        user: str,
    ) -> str:
        if len(user) <= 4:
            return "***"

        return f"{user[:3]}***{user[-2:]}"

    def _result(
        self,
        status: str,
        jobs: list[dict[str, Any]],
        checks: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        remote_hostname: str = "",
    ) -> dict[str, Any]:
        passed = (
            status
            == "cluster_readonly_preflight_passed"
        )

        return {
            "schema_version": "c11.3",
            "stage": "cluster_readonly_preflight",
            "status": status,
            "cluster": {
                "host": self.settings.host,
                "port": self.settings.port,
                "user": self._mask_user(
                    self.settings.user
                ),
                "remote_hostname": remote_hostname,
                "remote_root": self.settings.remote_root,
                "slurm_partition": (
                    self.settings.slurm_partition
                ),
                "vasp_module": self.settings.vasp_module,
                "vasp_executable": (
                    self.settings.vasp_executable
                ),
                "vasp_command": self.settings.vasp_command,
            },
            "job_count": len(jobs),
            "passed_count": (
                len(jobs) if passed else 0
            ),
            "failed_count": (
                0 if passed else len(jobs)
            ),
            "jobs": jobs,
            "eligible_jobs": (
                jobs if passed else []
            ),
            "checks": checks,
            "errors": errors,
            "upload_performed": False,
            "remote_write_performed": False,
            "submission_performed": False,
            "next_stage": (
                "c11.4_remote_submission_review"
            ),
        }