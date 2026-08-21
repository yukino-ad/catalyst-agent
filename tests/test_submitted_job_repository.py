import json
import tempfile
import unittest
from pathlib import Path

from app.domain.submitted_job_repository import SubmittedJobRepository


class SubmittedJobRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = SubmittedJobRepository(self.root)
        self.clean_slab_identity = {
            "calculation_type": "clean_slab_relax",
            "slab_id": "S1",
            "candidate_id": "C1",
            "atom_count": 48,
            "element_order": [
                "Cu",
                "Co",
                "Fe",
                "Ni",
                "Ti",
            ],
            "composition": {
                "Cu": 13,
                "Co": 8,
                "Fe": 8,
                "Ni": 8,
                "Ti": 11,
            },
            "energy_field": "final_toten_ev",
            "source_poscar_path": "C:/structures/S1.vasp",
            "vasp_config_version": "vasp-slab-v1",
        }
        self.job = {
            "job_id": "S1",
            "slurm_job_id": "123456",
            "remote_job_directory": "/work/runs/task-01/S1",
            "submitted_at": "2026-07-23T00:00:00+00:00",
            "submission_status": "submitted",
            "submission_performed": True,
            "scientific_identity": self.clean_slab_identity,
        }

    def tearDown(self):
        self.temporary.cleanup()

    def record(self, jobs=None):
        return self.repository.record_submission(
            "task-01", "c10_slab", "digest", jobs or [self.job]
        )

    def test_record_and_latest_are_written(self):
        result = self.record()
        self.assertEqual(result["status"], "submission_jobs_recorded")
        self.assertTrue((self.root / "records" / "123456.json").is_file())
        self.assertTrue((self.root / "latest_submission.json").is_file())

    def test_duplicate_is_idempotent(self):
        self.record()
        result = self.record()
        self.assertEqual(result["existing_count"], 1)

    def test_conflicting_identity_is_rejected(self):
        self.record()
        changed = {**self.job, "remote_job_directory": "/work/other/S1"}
        result = self.record([changed])
        self.assertEqual(result["status"], "submission_recording_failed")

    def test_invalid_or_unsubmitted_job_is_rejected(self):
        result = self.record([{**self.job, "slurm_job_id": "bad"}])
        self.assertEqual(result["failed_count"], 1)
        result = self.record([{**self.job, "submission_status": "failed"}])
        self.assertEqual(result["failed_count"], 1)

    def test_empty_is_skipped(self):
        result = self.repository.record_submission(
            "task-01", "c10_slab", "digest", []
        )
        self.assertEqual(result["status"], "submission_recording_skipped")

    def test_update_preserves_identity(self):
        self.record()
        updated = self.repository.update("123456", {
            "scheduler_state": "RUNNING",
        })
        self.assertEqual(updated["scheduler_state"], "RUNNING")
        with self.assertRaises(ValueError):
            self.repository.update("123456", {"task_id": "other"})

    def test_no_secrets_or_potcar_are_stored(self):
        self.record()
        text = json.dumps(self.repository.get("123456"))
        self.assertNotIn("PRIVATE KEY", text)
        self.assertNotIn("POTCAR", text)

    def test_clean_slab_identity_is_required(self):
        job = dict(self.job)
        job.pop("scientific_identity")
        result = self.record([job])
        self.assertEqual(
            result["status"],
            "submission_recording_failed",
        )
        self.assertIn(
            "requires scientific_identity",
            result["errors"][0]["message"],
        )

    def test_bulk_identity_is_required_and_persisted(self):
        identity = {
            "structure_id": "B1",
            "candidate_id": "C1",
            "calculation_type": "bulk_formation_relax",
            "composition": {"Cu": 1},
            "element_order": ["Cu"],
            "atom_count": 1,
            "energy_field": "final_toten_ev",
            "reference_data_version": "test-v1",
            "source_poscar_sha256": "a" * 64,
            "source_poscar_path": "C:/structures/B1.vasp",
            "vasp_config_version": "test-config",
        }
        result = self.repository.record_submission(
            "task-01", "c6d_bulk_formation", "digest",
            [{**self.job, "scientific_identity": identity}],
        )
        self.assertEqual(
            result["records"][0]["scientific_identity"], identity
        )


if __name__ == "__main__":
    unittest.main()
