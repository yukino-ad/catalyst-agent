import json
import tempfile
import unittest
from pathlib import Path

from app.domain.dft_local_preflight import (
    DFTLocalPreflightService,
)
from app.domain.submitted_job_repository import (
    SubmittedJobRepository,
)


def adsorption_identity() -> dict:
    return {
        "calculation_type": "adsorption_relax",
        "adsorption_structure_id": "A-CO-001",
        "candidate_id": "C1",
        "source_clean_slab_id": "S1",
        "site_id": "site-1",
        "site_type": "ontop",
        "adsorbate": "CO",
        "adsorbate_instance_count": 1,
        "coadsorption": False,
        "atom_count": 50,
        "element_order": ["Cu", "Co", "Fe", "Mn", "Al", "C", "O"],
        "composition": {
            "Cu": 10,
            "Co": 10,
            "Fe": 10,
            "Mn": 10,
            "Al": 8,
            "C": 1,
            "O": 1,
        },
        "energy_field": "final_toten_ev",
        "source_poscar_path": "data/adsorption/POSCAR",
        "source_poscar_sha256": "a" * 64,
        "vasp_config_version": "vasp-adsorption-v1",
    }


class AdsorptionExecutionIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = SubmittedJobRepository(
            self.root / "records"
        )
        self.job = {
            "job_id": "A-CO-001",
            "slurm_job_id": "123456",
            "remote_job_directory": (
                "/work/runs/task/A-CO-001"
            ),
            "submitted_at": "2026-07-24T00:00:00+00:00",
            "submission_status": "submitted",
            "submission_performed": True,
            "scientific_identity": adsorption_identity(),
        }

    def tearDown(self):
        self.temporary.cleanup()

    def _record(self, job=None):
        return self.repository.record_submission(
            task_id="ads-task",
            job_source="c12_5_adsorption",
            plan_digest="digest",
            jobs=[job or self.job],
        )

    def test_adsorption_identity_is_required_and_persisted(self):
        result = self._record()
        self.assertEqual(result["status"], "submission_jobs_recorded")
        self.assertEqual(
            result["records"][0]["scientific_identity"],
            adsorption_identity(),
        )

    def test_missing_identity_is_rejected(self):
        job = dict(self.job)
        job.pop("scientific_identity")
        result = self._record(job)
        self.assertEqual(result["failed_count"], 1)
        self.assertIn("requires scientific_identity", result["errors"][0]["message"])

    def test_coadsorption_identity_is_rejected(self):
        identity = adsorption_identity()
        identity["coadsorption"] = True
        result = self._record({**self.job, "scientific_identity": identity})
        self.assertEqual(result["failed_count"], 1)
        self.assertIn("Coadsorption", result["errors"][0]["message"])

    def test_atom_count_mismatch_is_rejected(self):
        identity = adsorption_identity()
        identity["atom_count"] = 51
        result = self._record({**self.job, "scientific_identity": identity})
        self.assertEqual(result["failed_count"], 1)
        self.assertIn("atom_count", result["errors"][0]["message"])

    def test_adsorption_directory_can_be_an_allowed_root(self):
        allowed = self.root / "data" / "adsorption_dft_inputs"
        job_dir = allowed / "task" / "job"
        job_dir.mkdir(parents=True)
        service = DFTLocalPreflightService(allowed_roots=[allowed])
        self.assertTrue(service._inside_allowed_root(job_dir.resolve()))

    def test_directory_outside_allowed_root_is_rejected(self):
        allowed = self.root / "allowed"
        outside = self.root / "outside" / "job"
        outside.mkdir(parents=True)
        service = DFTLocalPreflightService(allowed_roots=[allowed])
        self.assertFalse(service._inside_allowed_root(outside.resolve()))

    def test_identity_is_json_serializable(self):
        json.dumps(adsorption_identity(), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
