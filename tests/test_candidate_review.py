import json
import unittest

from app.domain.candidate_review import CandidateReviewGate


def candidate(index):
    return {
        "candidate_id": f"C{index}",
        "rank": index,
        "elements": ["Cu", "Fe", "Co", "Ni", "Mn"],
        "composition": {
            "Cu": 8, "Fe": 6, "Co": 6, "Ni": 6, "Mn": 6,
        },
        "total_score": 80.0 - index,
    }


class CandidateReviewGateTest(unittest.TestCase):
    def setUp(self):
        self.gate = CandidateReviewGate(max_selected=3)
        self.candidates = [candidate(i) for i in range(1, 6)]

    def test_classifies_all_decisions(self):
        result = self.gate.review(
            self.candidates,
            {
                "select": ["C1", "C2"],
                "reject": ["C3"],
                "defer": ["C4", "C5"],
            },
            total_candidate_count=100,
        )
        self.assertEqual(result["selected_count"], 2)
        self.assertEqual(result["rejected_count"], 1)
        self.assertEqual(result["deferred_count"], 2)
        self.assertEqual(result["unreviewed_candidate_count"], 95)
        self.assertTrue(result["ready_for_structure_modeling"])

    def test_unclassified_become_deferred(self):
        result = self.gate.review(
            self.candidates, {"select": ["C1"]}
        )
        self.assertEqual(result["deferred_count"], 4)
        self.assertEqual(
            result["unclassified_moved_to_defer"],
            ["C2", "C3", "C4", "C5"],
        )

    def test_more_than_three_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "At most 3"):
            self.gate.review(
                self.candidates,
                {"select": ["C1", "C2", "C3", "C4"]},
            )

    def test_conflicting_decisions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "multiple decisions"):
            self.gate.review(
                self.candidates,
                {"select": ["C1"], "reject": ["C1"]},
            )

    def test_unknown_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            self.gate.review(
                self.candidates, {"select": ["UNKNOWN"]}
            )

    def test_selecting_none_stops_modeling(self):
        result = self.gate.review(
            self.candidates,
            {"defer": ["C1", "C2", "C3", "C4", "C5"]},
        )
        self.assertFalse(result["ready_for_structure_modeling"])

    def test_result_is_json_serializable(self):
        result = self.gate.review(
            self.candidates, {"select": ["C1"]}
        )
        text = json.dumps(result, ensure_ascii=False)
        self.assertIn("candidate_review_completed", text)


if __name__ == "__main__":
    unittest.main()