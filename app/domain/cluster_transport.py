from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from app.domain.cluster_readonly_preflight import ClusterReadonlySettings


class ClusterTransportError(RuntimeError):
    pass


class ClusterTransport:
    """Restricted SSH/SCP transport shared by job operations."""

    def __init__(self, settings: ClusterReadonlySettings | None = None):
        self.settings = settings or ClusterReadonlySettings.from_environment()

    def run(self, remote_command: str, timeout: int | None = None) -> str:
        ssh = shutil.which("ssh")
        if not ssh:
            raise ClusterTransportError("Windows OpenSSH ssh was not found")
        completed = subprocess.run(
            [ssh, *self._options(), self._destination(), remote_command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or self.settings.timeout_seconds,
            check=False,
            shell=False,
        )
        if completed.returncode:
            raise ClusterTransportError(
                f"Remote command failed: {completed.stderr.strip()[:500]}"
            )
        return completed.stdout.strip()

    def download(self, remote_path: str, local_path: Path) -> None:
        scp = shutil.which("scp")
        if not scp:
            raise ClusterTransportError("Windows OpenSSH scp was not found")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                scp,
                "-P", str(self.settings.port),
                "-i", str(self.settings.key_path.resolve()),
                "-o", "BatchMode=yes",
                "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={self.settings.known_hosts_path.resolve()}",
                f"{self._destination()}:{remote_path}",
                str(local_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(self.settings.timeout_seconds, 120),
            check=False,
            shell=False,
        )
        if completed.returncode:
            raise ClusterTransportError(
                f"Download failed: {completed.stderr.strip()[:500]}"
            )

    def validate_remote_child(self, path: str, root: str) -> str:
        value = PurePosixPath(path)
        base = PurePosixPath(root)
        try:
            value.relative_to(base)
        except ValueError as error:
            raise ValueError("Remote path escaped configured root") from error
        if value == base or not value.is_absolute():
            raise ValueError("Remote path must be a child of configured root")
        return str(value)

    @staticmethod
    def quote(value: str) -> str:
        return shlex.quote(value)

    def _destination(self) -> str:
        return f"{self.settings.user}@{self.settings.host}"

    def _options(self) -> list[str]:
        return [
            "-T", "-p", str(self.settings.port),
            "-i", str(self.settings.key_path.resolve()),
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.settings.known_hosts_path.resolve()}",
        ]
