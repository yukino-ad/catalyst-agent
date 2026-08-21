import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from app.domain.formation_energy_backfill import FormationEnergyBackfillService


class FakeRepository:
    def __init__(self, record):
        self.record = record

    def get(self, slurm_job_id):
        if slurm_job_id == self.record.get("slurm_job_id"):
            return deepcopy(self.record)
        return None


class FormationEnergyBackfillServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reference_path = self.root / "references.json"
        self.config_path = self.root / "config.json"
        self.link_path = self.root / "link.json"
        self.output_root = self.root / "output"
        self.references = {
            "schema_version": "element-reference-energy-v1",
            "data_version": "test-v1",
            "status": "accepted",
            "energy_unit": "eV/atom",
            "source": "user_calculated",
            "references": {
                "Cu": {"energy_ev_atom": -3.0, "potcar": "Cu_pv"},
                "Au": {"energy_ev_atom": -2.0, "potcar": "Au"},
            },
        }
        self.config = {"potcar_mapping": {"Cu": "Cu_pv", "Au": "Au"}}
        self.link = {
            "task_id": "T1",
            "structure_id": "S1",
            "candidate_id": "C1",
            "alloy_slurm_job_id": "123",
            "job_source": "c6d_bulk_formation",
            "composition": {"Cu": 1, "Au": 1},
            "atom_count": 2,
            "alloy_energy_field": "final_toten_ev",
            "reference_data_version": "test-v1",
            "source_poscar_path": str(self.root / "original.vasp"),
        }
        self.record = {
            "slurm_job_id": "123",
            "task_id": "T1",
            "job_source": "c6d_bulk_formation",
            "scheduler_state": "COMPLETED",
            "vasp_decision": "completed_converged",
            "parsed_vasp_result": {
                "final_toten_ev": -5.8,
                "normal_termination": True,
                "required_accuracy_reached": True,
                "final_structure": {
                    "elements": ["Cu", "Au"],
                    "counts": [1, 1],
                    "atom_count": 2,
                },
            },
        }
        self._write_inputs()

    def tearDown(self):
        self.temp.cleanup()

    def _write_inputs(self):
        for path, value in (
            (self.reference_path, self.references),
            (self.config_path, self.config),
            (self.link_path, self.link),
        ):
            path.write_text(json.dumps(value), encoding="utf-8")

    def service(self):
        return FormationEnergyBackfillService(
            repository=FakeRepository(self.record),
            reference_path=self.reference_path,
            vasp_config_path=self.config_path,
            output_root=self.output_root,
        )

    def test_calculates_and_backfills_c7(self):
        result = self.service().calculate(self.link_path)
        self.assertAlmostEqual(result["formation_energy"], -0.4)
        self.assertEqual(result["formation_energy_status"], "dft_completed")
        self.assertTrue(result["c7_formation_energy_pass"])
        self.assertFalse(result["static_single_point_used"])
        self.assertTrue(Path(result["result_path"]).is_file())
        self.assertTrue(Path(result["c7_result_path"]).is_file())

    def test_missing_reference_is_rejected(self):
        del self.references["references"]["Au"]
        self._write_inputs()
        with self.assertRaisesRegex(ValueError, "Missing reference energy"):
            self.service().calculate(self.link_path)

    def test_potcar_mismatch_is_rejected(self):
        self.references["references"]["Cu"]["potcar"] = "Cu"
        self._write_inputs()
        with self.assertRaisesRegex(ValueError, "POTCAR mismatch"):
            self.service().calculate(self.link_path)

    def test_final_composition_mismatch_is_rejected(self):
        self.record["parsed_vasp_result"]["final_structure"]["counts"] = [2, 1]
        with self.assertRaisesRegex(ValueError, "CONTCAR composition"):
            self.service().calculate(self.link_path)

    def test_unconverged_job_is_rejected(self):
        self.record["vasp_decision"] = "incomplete"
        with self.assertRaisesRegex(ValueError, "not marked completed"):
            self.service().calculate(self.link_path)

    def test_wrong_job_source_is_rejected(self):
        self.record["job_source"] = "c10_slab"
        with self.assertRaisesRegex(ValueError, "not a C6D Bulk"):
            self.service().calculate(self.link_path)

    def test_missing_total_energy_is_rejected(self):
        self.record["parsed_vasp_result"]["final_toten_ev"] = None
        with self.assertRaisesRegex(ValueError, "must be a finite number"):
            self.service().calculate(self.link_path)

    def test_result_is_json_serializable(self):
        result = self.service().calculate(self.link_path)
        json.dumps(result, ensure_ascii=False)

    def test_calculate_from_persisted_scientific_identity(self):
        self.record["scientific_identity"] = {
            "structure_id": "S1",
            "candidate_id": "C1",
            "composition": {"Cu": 1, "Au": 1},
            "atom_count": 2,
            "energy_field": "final_toten_ev",
            "reference_data_version": "test-v1",
        }
        result = self.service().calculate_from_record("123")
        self.assertAlmostEqual(result["formation_energy"], -0.4)
        self.assertEqual(result["task_id"], "T1")


if __name__ == "__main__":
    unittest.main()
