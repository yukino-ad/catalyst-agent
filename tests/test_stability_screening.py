import json
import unittest

from app.domain.stability_screening import (
    StabilityScreeningEvaluator,
)


class StabilityScreeningEvaluatorTest(
    unittest.TestCase
):
    @staticmethod
    def structure(
        energy=0.03,
        energy_status="predicted",
    ):
        return {
            "structure_id": "S1",
            "candidate_id": "C1",
            "elements": [
                "Cu", "Al", "Co", "Cr", "Mn",
            ],
            "composition": {
                "Cu": 8,
                "Al": 3,
                "Co": 7,
                "Cr": 7,
                "Mn": 7,
            },
            "formation_energy": energy,
            "formation_energy_status": energy_status,
            "eligible_for_slab": False,
        }

    def test_all_criteria_pass(self):
        result = StabilityScreeningEvaluator().evaluate([
            self.structure()
        ])

        structure = result["structures"][0]

        self.assertTrue(
            structure["formation_energy_pass"]
        )
        self.assertTrue(
            structure["solid_solution_pass"]
        )
        self.assertTrue(
            structure["eligible_for_slab"]
        )
        self.assertEqual(
            structure["stability_decision"],
            "passed",
        )

    def test_energy_equal_to_threshold_fails(self):
        result = StabilityScreeningEvaluator().evaluate([
            self.structure(energy=0.05)
        ])

        structure = result["structures"][0]

        self.assertFalse(
            structure["formation_energy_pass"]
        )
        self.assertFalse(
            structure["eligible_for_slab"]
        )

    def test_waiting_for_dft_remains_pending(self):
        structure = self.structure(
            energy=None,
            energy_status="waiting_for_dft",
        )
        structure["elements"] = [
            "Cu", "Au", "Ag", "Pt", "Pd",
        ]
        structure["composition"] = {
            "Cu": 8,
            "Au": 6,
            "Ag": 6,
            "Pt": 6,
            "Pd": 6,
        }

        result = StabilityScreeningEvaluator().evaluate([
            structure
        ])

        evaluated = result["structures"][0]

        self.assertIsNone(
            evaluated["formation_energy_pass"]
        )
        self.assertEqual(
            evaluated["stability_decision"],
            "waiting_for_formation_energy",
        )
        self.assertFalse(
            evaluated["eligible_for_slab"]
        )

    def test_empty_input_is_skipped(self):
        result = StabilityScreeningEvaluator().evaluate([])

        self.assertEqual(
            result["status"],
            "stability_screening_skipped",
        )

    def test_json_serializable(self):
        result = StabilityScreeningEvaluator().evaluate([])
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()