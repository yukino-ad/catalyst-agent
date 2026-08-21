import json
import unittest

from app.domain.adsorption_structure_review import (
    AdsorptionStructureReviewGate,
)


def structure(identifier, eligible=True):
    return {
        "adsorption_structure_id": identifier,
        "eligible_for_adsorption_review": eligible,
        "adsorbate_instance_count": 1,
        "coadsorption": False,
    }


class AdsorptionStructureReviewGateTest(unittest.TestCase):
    def setUp(self):
        self.gate = AdsorptionStructureReviewGate(max_approved=15)
        self.structures = [
            structure("A"),
            structure("B"),
            structure("C"),
        ]

    def test_approve_reject_and_defer(self):
        result = self.gate.review(
            self.structures,
            {
                "approve": ["A"],
                "reject": ["B"],
                "defer": ["C"],
                "note": "reviewed",
            },
        )
        self.assertEqual(result["approved_count"], 1)
        self.assertEqual(result["rejected_count"], 1)
        self.assertEqual(result["deferred_count"], 1)
        self.assertTrue(result["approved_for_adsorption_dft"])

    def test_unclassified_structure_becomes_deferred(self):
        result = self.gate.review(
            self.structures,
            {"approve": ["A"]},
        )
        self.assertEqual(
            [item["adsorption_structure_id"] for item in result["deferred"]],
            ["B", "C"],
        )

    def test_quality_failed_structure_cannot_be_reviewed(self):
        with self.assertRaisesRegex(ValueError, "did not pass"):
            self.gate.review([structure("A", eligible=False)], {})

    def test_single_adsorbate_violation_is_rejected(self):
        invalid = structure("A")
        invalid["adsorbate_instance_count"] = 2
        with self.assertRaisesRegex(ValueError, "single-adsorbate"):
            self.gate.review([invalid], {})

    def test_conflicting_decisions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "multiple decisions"):
            self.gate.review(
                self.structures,
                {"approve": ["A"], "reject": ["A"]},
            )

    def test_unknown_identifier_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            self.gate.review(
                self.structures,
                {"approve": ["UNKNOWN"]},
            )

    def test_more_than_fifteen_approvals_are_rejected(self):
        values = [structure(f"S{index}") for index in range(16)]
        with self.assertRaisesRegex(ValueError, "At most 15"):
            self.gate.review(
                values,
                {"approve": [item["adsorption_structure_id"] for item in values]},
            )

    def test_result_is_json_serializable(self):
        result = self.gate.review(
            self.structures,
            {"approve": ["A"]},
        )
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
