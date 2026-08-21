import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.domain.cluster_readonly_preflight import (
    ClusterReadonlySettings,
)
from app.domain.remote_execution_plan import (
    RemoteExecutionPlanService,
)
from app.domain.remote_submission import (
    RemoteSubmissionService,
    RemoteSubmissionSettings,
)


class RemoteSubmissionServiceTest(unittest.TestCase):
    FILE_NAMES = {
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "POTCAR",
        "vasp.slurm",
    }

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.job_directory = self.root / "S1"
        self.job_directory.mkdir()

        for name in self.FILE_NAMES:
            (self.job_directory / name).write_text(
                f"content for {name}\n",
                encoding="utf-8",
                newline="\n",
            )

        self.remote_root = (
            "/work/home/test_user/catalyst-agent/runs"
        )
        self.plan = RemoteExecutionPlanService(
            remote_runs_root=self.remote_root,
        ).plan(
            jobs=[{
                "job_id": "S1",
                "job_dir": str(self.job_directory),
            }],
            task_id="task-01",
            job_source="c10_slab",
        )
        self.verified_job = {
            **self.plan["jobs"][0],
            "remote_hash_verified": True,
            "upload_status": "uploaded_and_verified",
        }
        self.review = {
            "status": "remote_submission_approved",
            "approved_job_ids": ["S1"],
            "plan_digest": self.plan["plan_digest"],
            "confirmation_text": "SUBMIT task-01",
        }

        ssh = ClusterReadonlySettings(
            enabled=True,
            host="cluster.example.edu",
            port=22,
            user="test_user",
            key_path=self.root / "cluster_key",
            known_hosts_path=self.root / "known_hosts",
            timeout_seconds=20,
            remote_root=(
                "/work/home/test_user/catalyst-agent"
            ),
            slurm_partition="normal",
            vasp_module="vasp-test",
            vasp_executable="vasp_std",
            vasp_command="srun vasp_std",
        )
        ssh.key_path.write_text("test key", encoding="utf-8")
        ssh.known_hosts_path.write_text(
            "cluster test key",
            encoding="utf-8",
        )
        self.settings = RemoteSubmissionSettings(
            enabled=True,
            timeout_seconds=20,
            remote_runs_root=self.remote_root,
            slurm_script_name="vasp.slurm",
            ssh=ssh,
        )
        self.service = RemoteSubmissionService(
            settings=self.settings,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def submit(self):
        return self.service.submit(
            plan=self.plan,
            verified_jobs=[self.verified_job],
            review=self.review,
        )

    def test_disabled_switch_never_calls_remote(self):
        service = RemoteSubmissionService(
            settings=replace(
                self.settings,
                enabled=False,
            )
        )

        with patch.object(
            service,
            "_run_submission_command",
        ) as mocked_submit:
            result = service.submit(
                self.plan,
                [self.verified_job],
                self.review,
            )

        self.assertEqual(
            result["status"],
            "remote_submission_disabled",
        )
        mocked_submit.assert_not_called()
        self.assertFalse(result["submission_performed"])

    def test_plan_digest_mismatch_is_rejected(self):
        review = {
            **self.review,
            "plan_digest": "wrong",
        }

        with self.assertRaisesRegex(ValueError, "digest"):
            self.service.submit(
                self.plan,
                [self.verified_job],
                review,
            )

    def test_plan_mutation_after_approval_is_rejected(self):
        plan = json.loads(json.dumps(self.plan))
        plan["jobs"][0]["remote_job_directory"] = (
            f"{self.remote_root}/task-01/changed"
        )

        with self.assertRaisesRegex(
            ValueError,
            "changed after approval",
        ):
            self.service.submit(
                plan,
                [self.verified_job],
                self.review,
            )

    def test_confirmation_phrase_is_required(self):
        review = {
            **self.review,
            "confirmation_text": "SUBMIT other-task",
        }

        with self.assertRaisesRegex(
            ValueError,
            "confirmation",
        ):
            self.service.submit(
                self.plan,
                [self.verified_job],
                review,
            )

    def test_unverified_job_is_rejected(self):
        job = {
            **self.verified_job,
            "remote_hash_verified": False,
        }

        with self.assertRaisesRegex(
            ValueError,
            "not verified",
        ):
            self.service.submit(
                self.plan,
                [job],
                self.review,
            )

    def test_remote_path_escape_is_rejected(self):
        job = {
            **self.verified_job,
            "remote_job_directory": "/work/other/S1",
        }
        plan = json.loads(json.dumps(self.plan))
        plan["jobs"][0]["remote_job_directory"] = (
            "/work/other/S1"
        )
        plan["plan_digest"] = (
            RemoteExecutionPlanService._plan_digest(
                task_id=plan["task_id"],
                job_source=plan["job_source"],
                batch_directory=plan[
                    "remote_batch_directory"
                ],
                jobs=plan["jobs"],
            )
        )
        review = {
            **self.review,
            "plan_digest": plan["plan_digest"],
        }

        result = self.service.submit(
            plan,
            [job],
            review,
        )

        self.assertEqual(
            result["status"],
            "remote_submission_failed",
        )
        self.assertIn(
            "escaped",
            result["errors"][0]["message"],
        )

    def test_numeric_job_id_is_stored(self):
        with patch.object(
            self.service,
            "_run_submission_command",
            return_value="123456",
        ):
            result = self.submit()

        self.assertEqual(
            result["status"],
            "remote_submission_completed",
        )
        self.assertEqual(result["slurm_job_ids"], ["123456"])
        self.assertTrue(result["submission_performed"])

    def test_federated_job_id_is_parsed(self):
        self.assertEqual(
            self.service._parse_slurm_job_id(
                "123456;cluster-name"
            ),
            "123456",
        )

    def test_timeout_is_unknown_and_not_retried(self):
        with (
            patch(
                "app.domain.remote_submission.shutil.which",
                return_value="ssh",
            ),
            patch(
                "app.domain.remote_submission.subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["ssh"],
                    timeout=20,
                ),
            ) as mocked_run,
        ):
            result = self.submit()

        self.assertEqual(mocked_run.call_count, 1)
        self.assertEqual(
            result["status"],
            "remote_submission_unknown",
        )
        self.assertFalse(result["automatic_retry_allowed"])

    def test_submission_command_rechecks_hashes(self):
        with patch.object(
            self.service,
            "_run_ssh_for_submission",
            return_value="123456",
        ) as mocked_ssh:
            output = self.service._run_submission_command(
                self.verified_job
            )

        command = mocked_ssh.call_args.args[0]
        self.assertEqual(output, "123456")
        self.assertIn("sha256sum --check --status", command)
        self.assertIn("sbatch --parsable vasp.slurm", command)
        self.assertLess(
            command.index("sha256sum --check --status"),
            command.index("sbatch --parsable vasp.slurm"),
        )

    def test_result_is_json_serializable(self):
        service = RemoteSubmissionService(
            settings=replace(
                self.settings,
                enabled=False,
            )
        )
        result = service.submit(
            self.plan,
            [self.verified_job],
            self.review,
        )

        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
