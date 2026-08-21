import json
import unittest

from app.domain.slab_review import SlabReviewGate


def slab(index: int) -> dict:
    return {
        "slab_id": f"S{index}",
        "candidate_id": f"C{index}",
        "atom_count": 48,
        "poscar_path": f"S{index}.vasp",
        "quality_decision": "passed",
        "eligible_for_dft_review": True,
    }


class SlabReviewGateTest(unittest.TestCase):
    def setUp(self):
        self.gate = SlabReviewGate(max_approved=3)
        self.slabs = [slab(1), slab(2), slab(3)]

    def test_classifies_decisions(self):
        result = self.gate.review(
            self.slabs,
            {
                "approve": ["S1"],
                "reject": ["S2"],
                "defer": ["S3"],
                "note": "manual review",
            },
        )

        self.assertEqual(result["approved_count"], 1)
        self.assertEqual(result["rejected_count"], 1)
        self.assertEqual(result["deferred_count"], 1)
        self.assertTrue(result["approved_for_dft"])

    def test_unclassified_is_deferred(self):
        result = self.gate.review(
            self.slabs,
            {"approve": ["S1"]},
        )

        self.assertEqual(result["deferred_count"], 2)

    def test_failed_quality_cannot_be_reviewed(self):
        bad = slab(1)
        bad["eligible_for_dft_review"] = False

        with self.assertRaisesRegex(
            ValueError,
            "did not pass",
        ):
            self.gate.review([bad], {})

    def test_json_serializable(self):
        result = self.gate.review(
            self.slabs,
            {"approve": ["S1"]},
        )
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()