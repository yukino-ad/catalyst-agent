import json
import unittest
from pathlib import Path


class FormationEnergyReferenceTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(
            "database/formation_energy_references/element_reference_energies_v1.json"
        )
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def test_reference_database_is_accepted_and_complete(self):
        self.assertEqual(self.data["status"], "accepted")
        self.assertEqual(self.data["energy_unit"], "eV/atom")
        self.assertEqual(self.data["source"], "user_calculated")
        self.assertEqual(len(self.data["references"]), 16)

    def test_real_job_elements_use_expected_potcars(self):
        expected = {
            "Cu": "Cu_pv", "Au": "Au", "Co": "Co_pv",
            "Fe": "Fe_pv", "Ni": "Ni_pv",
        }
        for element, potcar in expected.items():
            self.assertEqual(
                self.data["references"][element]["potcar"], potcar
            )

    def test_reference_database_is_json_serializable(self):
        json.dumps(self.data, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
