import unittest

from app.api.stage_outputs import safe_stage_outputs


class ApiStageOutputsTest(unittest.TestCase):
    def test_c6_keeps_scientific_values_without_paths(self):
        output = {
            "formation_energy_evaluation": {
                "status": "formation_energy_completed",
                "structure_count": 1,
                "structures": [{
                    "structure_id": "S1",
                    "composition": {"Cu": 6, "Fe": 6},
                    "formation_energy_ev_per_atom": -0.0574,
                    "formation_energy_status": "predicted",
                    "cif_path": "private/path.cif",
                    "POTCAR": "secret",
                }],
            }
        }
        result = safe_stage_outputs(output, "formation_energy")
        self.assertEqual(result["items"][0]["structure_id"], "S1")
        self.assertEqual(result["items"][0]["formation_energy_ev_per_atom"], -0.0574)
        self.assertNotIn("private/path.cif", str(result))
        self.assertNotIn("secret", str(result))

    def test_c7_keeps_each_structure_decision(self):
        output = {
            "stability_screening": {
                "passed_count": 1,
                "failed_count": 1,
                "structures": [
                    {"structure_id": "S1", "delta_percent": 4.2, "omega": 1.5, "stability_decision": "passed"},
                    {"structure_id": "S2", "delta_percent": 7.1, "omega": 0.9, "stability_decision": "failed"},
                ],
            }
        }
        result = safe_stage_outputs(output, "stability_screening")
        self.assertEqual([item["stability_decision"] for item in result["items"]], ["passed", "failed"])

    def test_c6_normalizes_runtime_energy_field_and_unit(self):
        result = safe_stage_outputs(
            {
                "formation_energy_structures": [{
                    "structure_id": "S1",
                    "formation_energy": -0.05748231,
                    "formation_energy_unit": "eV/atom",
                    "formation_energy_status": "predicted",
                }]
            },
            "formation_energy",
        )
        self.assertEqual(
            result["items"][0]["formation_energy_ev_per_atom"],
            -0.05748231,
        )
        self.assertEqual(result["items"][0]["formation_energy_unit"], "eV/atom")


if __name__ == "__main__":
    unittest.main()
