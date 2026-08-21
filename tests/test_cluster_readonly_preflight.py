import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.domain.cluster_readonly_preflight import (
    ClusterReadonlyPreflightService,
    ClusterReadonlySettings,
)


class ClusterReadonlyPreflightServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        root = Path(self.temp_directory.name)

        self.key_path = root / "cluster_key"
        self.key_path.write_text(
            "test-key",
            encoding="utf-8",
        )

        self.known_hosts_path = (
            root / "known_hosts"
        )
        self.known_hosts_path.write_text(
            "cluster ssh-ed25519 test",
            encoding="utf-8",
        )

        self.settings = ClusterReadonlySettings(
            enabled=True,
            host="eshell111.hpccube.com",
            port=65082,
            user="test_user",
            key_path=self.key_path,
            known_hosts_path=self.known_hosts_path,
            timeout_seconds=20,
            remote_root=(
                "/work/home/test_user/catalyst-agent"
            ),
            slurm_partition="xahcnormal",
            vasp_module=(
                "vasp-5.4.4-intelmpi2017_ioptcell"
            ),
            vasp_executable="vasp_std",
            vasp_command=(
                "srun --mpi=pmi2 vasp_std"
            ),
        )

        self.jobs = [{
            "job_id": "S1",
            "local_preflight_passed": True,
        }]

    def tearDown(self):
        self.temp_directory.cleanup()

    @staticmethod
    def successful_stdout() -> str:
        return (
            "connection=ok\n"
            "hostname=login09\n"
            "remote_root=ok\n"
            "sbatch=ok\n"
            "squeue=ok\n"
            "sinfo=ok\n"
            "partition=ok\n"
            "module=ok\n"
            "vasp_executable=ok\n"
        )

    @patch(
        "app.domain.cluster_readonly_preflight"
        ".shutil.which",
        return_value="ssh.exe",
    )
    @patch(
        "app.domain.cluster_readonly_preflight"
        ".subprocess.run",
    )
    def test_valid_environment_passes(
        self,
        mocked_run,
        mocked_which,
    ):
        mocked_run.return_value = (
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=self.successful_stdout(),
                stderr="",
            )
        )

        result = (
            ClusterReadonlyPreflightService(
                settings=self.settings,
            ).inspect(self.jobs)
        )

        self.assertEqual(
            result["status"],
            "cluster_readonly_preflight_passed",
        )
        self.assertEqual(result["passed_count"], 1)
        self.assertEqual(
            result["eligible_jobs"],
            self.jobs,
        )
        self.assertFalse(
            result["upload_performed"]
        )
        self.assertFalse(
            result["remote_write_performed"]
        )
        self.assertFalse(
            result["submission_performed"]
        )

        command = mocked_run.call_args.args[0]

        self.assertIn(
            "BatchMode=yes",
            command,
        )
        self.assertIn(
            "StrictHostKeyChecking=yes",
            command,
        )
        self.assertNotIn("scp", command)
        self.assertNotIn("sbatch --parsable", command)

    def test_empty_jobs_are_skipped(self):
        result = (
            ClusterReadonlyPreflightService(
                settings=self.settings,
            ).inspect([])
        )

        self.assertEqual(
            result["status"],
            "cluster_readonly_preflight_skipped",
        )

    def test_disabled_configuration_is_blocked(self):
        disabled = replace(
            self.settings,
            enabled=False,
        )

        result = (
            ClusterReadonlyPreflightService(
                settings=disabled,
            ).inspect(self.jobs)
        )

        self.assertEqual(
            result["status"],
            "cluster_readonly_preflight_disabled",
        )
        self.assertEqual(
            result["eligible_jobs"],
            [],
        )

    @patch(
        "app.domain.cluster_readonly_preflight"
        ".shutil.which",
        return_value="ssh.exe",
    )
    @patch(
        "app.domain.cluster_readonly_preflight"
        ".subprocess.run",
    )
    def test_missing_vasp_fails(
        self,
        mocked_run,
        mocked_which,
    ):
        mocked_run.return_value = (
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    self.successful_stdout().replace(
                        "vasp_executable=ok",
                        "vasp_executable=missing",
                    )
                ),
                stderr="",
            )
        )

        result = (
            ClusterReadonlyPreflightService(
                settings=self.settings,
            ).inspect(self.jobs)
        )

        self.assertEqual(
            result["status"],
            "cluster_readonly_preflight_failed",
        )
        self.assertEqual(
            result["eligible_jobs"],
            [],
        )

    @patch(
        "app.domain.cluster_readonly_preflight"
        ".shutil.which",
        return_value="ssh.exe",
    )
    @patch(
        "app.domain.cluster_readonly_preflight"
        ".subprocess.run",
        side_effect=subprocess.TimeoutExpired(
            cmd="ssh",
            timeout=20,
        ),
    )
    def test_timeout_is_reported(
        self,
        mocked_run,
        mocked_which,
    ):
        result = (
            ClusterReadonlyPreflightService(
                settings=self.settings,
            ).inspect(self.jobs)
        )

        self.assertEqual(
            result["status"],
            "cluster_readonly_preflight_failed",
        )
        self.assertTrue(result["errors"])

    def test_invalid_remote_root_is_blocked(self):
        unsafe = replace(
            self.settings,
            remote_root=(
                "/work/test; rm -rf something"
            ),
        )

        result = (
            ClusterReadonlyPreflightService(
                settings=unsafe,
            ).inspect(self.jobs)
        )

        self.assertEqual(
            result["status"],
            "cluster_readonly_preflight_failed",
        )

    def test_result_is_json_serializable(self):
        result = (
            ClusterReadonlyPreflightService(
                settings=replace(
                    self.settings,
                    enabled=False,
                ),
            ).inspect(self.jobs)
        )

        json.dumps(
            result,
            ensure_ascii=False,
        )


if __name__ == "__main__":
    unittest.main()