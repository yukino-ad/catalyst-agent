import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.domain.remote_execution_plan import (
    RemoteExecutionPlanService,
)


class RemoteExecutionPlanServiceTest(
    unittest.TestCase
):
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

        self.service = RemoteExecutionPlanService(
            remote_runs_root=(
                "/work/home/test_user/"
                "catalyst-agent/runs"
            )
        )
        self.jobs = [{
            "job_id": "S1",
            "job_dir": str(self.job_directory),
            "local_preflight_passed": True,
        }]

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_valid_five_files_create_plan(self):
        result = self._plan()

        self.assertEqual(
            result["status"],
            "remote_execution_plan_ready",
        )
        self.assertEqual(result["job_count"], 1)
        self.assertEqual(
            result["jobs"][0]["file_count"],
            5,
        )
        self.assertEqual(
            result["jobs"][0][
                "remote_job_directory"
            ],
            (
                "/work/home/test_user/"
                "catalyst-agent/runs/task-01/S1"
            ),
        )

    def test_empty_jobs_are_skipped(self):
        result = self.service.plan(
            jobs=[],
            task_id="task-01",
            job_source="c10_slab",
        )

        self.assertEqual(
            result["status"],
            "remote_execution_plan_skipped",
        )

    def test_missing_file_is_rejected(self):
        (self.job_directory / "INCAR").unlink()

        with self.assertRaisesRegex(
            ValueError,
            "exactly",
        ):
            self._plan()

    def test_extra_file_is_rejected(self):
        (self.job_directory / "extra.txt").write_text(
            "extra",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "exactly",
        ):
            self._plan()

    def test_unsafe_task_id_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "task_id",
        ):
            self.service.plan(
                jobs=self.jobs,
                task_id="task;rm",
                job_source="c10_slab",
            )

    def test_unsafe_job_id_is_rejected(self):
        jobs = [{
            **self.jobs[0],
            "job_id": "../S1",
        }]

        with self.assertRaisesRegex(
            ValueError,
            "job_id",
        ):
            self.service.plan(
                jobs=jobs,
                task_id="task-01",
                job_source="c10_slab",
            )

    def test_unsafe_remote_root_is_rejected(self):
        service = RemoteExecutionPlanService(
            remote_runs_root="/work/test;rm"
        )

        with self.assertRaisesRegex(
            ValueError,
            "CLUSTER_REMOTE_RUNS_ROOT",
        ):
            service.plan(
                jobs=self.jobs,
                task_id="task-01",
                job_source="c10_slab",
            )

    def test_file_sha256_matches_local_content(self):
        result = self._plan()
        files = {
            item["name"]: item
            for item in result["jobs"][0]["files"]
        }
        path = self.job_directory / "POSCAR"
        expected = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        self.assertEqual(
            files["POSCAR"]["sha256"],
            expected,
        )

    def test_result_is_json_serializable(self):
        json.dumps(
            self._plan(),
            ensure_ascii=False,
        )

    def test_plan_never_writes_or_submits(self):
        result = self._plan()

        self.assertFalse(
            result["remote_write_performed"]
        )
        self.assertFalse(
            result["upload_performed"]
        )
        self.assertFalse(
            result["submission_performed"]
        )

    def _plan(self) -> dict:
        return self.service.plan(
            jobs=self.jobs,
            task_id="task-01",
            job_source="c10_slab",
        )


if __name__ == "__main__":
    unittest.main()
