import json
import tempfile
import unittest
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.domain.cluster_readonly_preflight import (
    ClusterReadonlySettings,
)
from app.domain.remote_execution_plan import (
    RemoteExecutionPlanService,
)
from app.domain.remote_upload import (
    RemoteUploadError,
    RemoteUploadService,
    RemoteUploadSettings,
)


class RemoteUploadServiceTest(unittest.TestCase):
    FILE_NAMES = {
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "POTCAR",
        "vasp.slurm",
    }

    def setUp(self):
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )
        self.root = Path(
            self.temporary_directory.name
        )
        self.job_directory = self.root / "S1"
        self.job_directory.mkdir()

        for name in self.FILE_NAMES:
            (self.job_directory / name).write_text(
                f"content for {name}\n",
                encoding="utf-8",
                newline="\n",
            )

        self.remote_root = (
            "/work/home/test_user/"
            "catalyst-agent/runs"
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
        self.review = {
            "status": "remote_upload_approved",
            "approved_job_ids": ["S1"],
            "plan_digest": self.plan["plan_digest"],
            "confirmation_text": "UPLOAD task-01",
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
        ssh.key_path.write_text(
            "test key",
            encoding="utf-8",
        )
        ssh.known_hosts_path.write_text(
            "cluster test key",
            encoding="utf-8",
        )
        self.settings = RemoteUploadSettings(
            enabled=True,
            timeout_seconds=20,
            remote_runs_root=self.remote_root,
            ssh=ssh,
        )
        self.service = RemoteUploadService(
            settings=self.settings,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_disabled_switch_never_calls_remote(self):
        service = RemoteUploadService(
            settings=replace(
                self.settings,
                enabled=False,
            )
        )

        with patch.object(
            service,
            "_run_ssh",
        ) as mocked_ssh:
            result = service.upload(
                self.plan,
                self.review,
            )

        self.assertEqual(
            result["status"],
            "remote_upload_disabled",
        )
        mocked_ssh.assert_not_called()
        self.assertFalse(result["upload_performed"])
        self.assertFalse(
            result["submission_performed"]
        )

    def test_plan_digest_mismatch_is_rejected(self):
        review = {
            **self.review,
            "plan_digest": "wrong",
        }

        with self.assertRaisesRegex(
            ValueError,
            "digest",
        ):
            self.service.upload(self.plan, review)

    def test_plan_mutation_after_approval_is_rejected(self):
        plan = json.loads(json.dumps(self.plan))
        plan["jobs"][0]["remote_job_directory"] = (
            f"{self.remote_root}/task-01/changed"
        )

        with self.assertRaisesRegex(
            ValueError,
            "changed after approval",
        ):
            self.service.upload(plan, self.review)

    def test_confirmation_phrase_is_required(self):
        review = {
            **self.review,
            "confirmation_text": "UPLOAD something-else",
        }

        with self.assertRaisesRegex(
            ValueError,
            "confirmation",
        ):
            self.service.upload(self.plan, review)

    def test_unknown_job_id_is_rejected(self):
        review = {
            **self.review,
            "approved_job_ids": ["UNKNOWN"],
        }

        with self.assertRaisesRegex(
            ValueError,
            "Unknown",
        ):
            self.service.upload(self.plan, review)

    def test_changed_local_file_fails_before_remote_write(self):
        (self.job_directory / "INCAR").write_text(
            "changed\n",
            encoding="utf-8",
        )

        with patch.object(
            self.service,
            "_run_ssh",
        ) as mocked_ssh:
            result = self.service.upload(
                self.plan,
                self.review,
            )

        self.assertEqual(
            result["status"],
            "remote_upload_failed",
        )
        mocked_ssh.assert_not_called()
        self.assertFalse(
            result["remote_write_performed"]
        )

    def test_remote_path_escape_is_rejected(self):
        plan = json.loads(json.dumps(self.plan))
        plan["jobs"][0]["remote_job_directory"] = (
            "/work/home/other/S1"
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

        result = self.service.upload(
            plan,
            review,
        )

        self.assertEqual(
            result["status"],
            "remote_upload_failed",
        )
        self.assertIn(
            "escaped",
            result["errors"][0]["message"],
        )

    def test_existing_verified_remote_directory_is_reused(self):
        hashes = {
            item["name"]: item["sha256"]
            for item in self.plan["jobs"][0]["files"]
        }
        with (
            patch.object(
                self.service, "_discover_remote_state",
                return_value={"kind": "final", "path": "final"},
            ),
            patch.object(
                self.service, "_remote_hashes", return_value=hashes,
            ),
            patch.object(self.service, "_upload_files") as mocked_upload,
        ):
            result = self.service.upload(
                self.plan,
                self.review,
            )

        self.assertEqual(
            result["status"], "remote_upload_verified",
        )
        self.assertEqual(
            result["jobs"][0]["upload_status"],
            "existing_remote_verified",
        )
        mocked_upload.assert_not_called()
        self.assertFalse(result["upload_performed"])

    def test_scp_failure_never_verifies_or_finalizes(self):
        with (
            patch.object(
                self.service, "_discover_remote_state",
                return_value={"kind": "new", "path": ""},
            ),
            patch.object(self.service, "_prepare_staging_directory"),
            patch.object(
                self.service, "_remote_hashes", return_value={},
            ),
            patch.object(
                self.service,
                "_upload_files",
                side_effect=RemoteUploadError(
                    "scp failed"
                ),
            ),
        ):
            result = self.service.upload(
                self.plan,
                self.review,
            )

        self.assertFalse(
            result["jobs"][0]["remote_hash_verified"]
        )
        self.assertFalse(
            result["submission_performed"]
        )

    def test_remote_hash_mismatch_fails(self):
        hashes = {
            name: "0" * 64
            for name in self.FILE_NAMES
        }

        with (
            patch.object(
                self.service, "_discover_remote_state",
                return_value={"kind": "new", "path": ""},
            ),
            patch.object(self.service, "_prepare_staging_directory"),
            patch.object(self.service, "_upload_files"),
            patch.object(
                self.service,
                "_remote_hashes",
                side_effect=[{}, hashes],
            ),
            patch.object(self.service, "_run_ssh", return_value=""),
        ):
            result = self.service.upload(
                self.plan,
                self.review,
            )

        self.assertEqual(
            result["status"],
            "remote_upload_failed",
        )
        self.assertTrue(result["upload_performed"])
        self.assertFalse(
            result["jobs"][0]["remote_hash_verified"]
        )

    def test_matching_hashes_are_verified(self):
        hashes = {
            item["name"]: item["sha256"]
            for item in self.plan["jobs"][0]["files"]
        }

        with (
            patch.object(
                self.service, "_discover_remote_state",
                return_value={"kind": "new", "path": ""},
            ),
            patch.object(self.service, "_prepare_staging_directory"),
            patch.object(
                self.service,
                "_upload_files",
            ) as mocked_upload,
            patch.object(
                self.service,
                "_remote_hashes",
                side_effect=[{}, hashes],
            ),
            patch.object(self.service, "_run_ssh", return_value=""),
        ):
            result = self.service.upload(
                self.plan,
                self.review,
            )

        self.assertEqual(
            result["status"],
            "remote_upload_verified",
        )
        self.assertEqual(result["verified_count"], 1)
        self.assertEqual(mocked_upload.call_count, 1)
        self.assertEqual(len(mocked_upload.call_args.kwargs["local_paths"]), 5)
        self.assertFalse(
            result["submission_performed"]
        )

    def test_resumes_staging_and_uploads_only_missing_file(self):
        expected = {
            item["name"]: item["sha256"]
            for item in self.plan["jobs"][0]["files"]
        }
        partial = {
            name: digest for name, digest in expected.items()
            if name != "vasp.slurm"
        }
        with (
            patch.object(
                self.service, "_discover_remote_state",
                return_value={
                    "kind": "staging",
                    "path": f"{self.remote_root}/task-01/S1.uploading-old",
                },
            ),
            patch.object(
                self.service, "_remote_hashes",
                side_effect=[partial, expected],
            ),
            patch.object(self.service, "_upload_files") as mocked_upload,
            patch.object(self.service, "_run_ssh", return_value=""),
        ):
            result = self.service.upload(self.plan, self.review)
        self.assertEqual(result["status"], "remote_upload_verified")
        paths = mocked_upload.call_args.kwargs["local_paths"]
        self.assertEqual([path.name for path in paths], ["vasp.slurm"])
        self.assertTrue(result["jobs"][0]["resumed_staging_upload"])

    def test_transient_connection_timeout_is_retried(self):
        transient = subprocess.CompletedProcess(
            args=["scp"], returncode=255, stdout="",
            stderr="ssh: connect to host cluster port 22: Connection timed out",
        )
        success = subprocess.CompletedProcess(
            args=["scp"], returncode=0, stdout="ok\n", stderr="",
        )
        service = RemoteUploadService(settings=replace(
            self.settings, retry_attempts=3, retry_delay_seconds=0,
        ))
        with patch("app.domain.remote_upload.subprocess.run", side_effect=[
            transient, success,
        ]) as mocked_run:
            output = service._run_process(["scp"], "upload job files")
        self.assertEqual(output, "ok")
        self.assertEqual(mocked_run.call_count, 2)

    def test_result_is_json_serializable(self):
        service = RemoteUploadService(
            settings=replace(
                self.settings,
                enabled=False,
            )
        )
        result = service.upload(
            self.plan,
            self.review,
        )

        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
