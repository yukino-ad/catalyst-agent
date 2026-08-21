import unittest

from app.domain.candidate_constraints import (
    CandidateConstraintBuilder,
)
from app.domain.candidate_evaluator import (
    CandidateEvaluator,
    DEFAULT_WEIGHTS,
)


class CandidateEvaluatorTest(unittest.TestCase):
    def setUp(self):
        self.evaluator = CandidateEvaluator()
        self.constraints = CandidateConstraintBuilder().build(
            {
                "reaction_id": "CO2RR_CO",
                "reaction_family": "CO2RR",
                "target_product": "CO",
                "material_family": "high_entropy_alloy",
            },
            accepted_papers=[{
                "evidence_id": "E1",
                "paper_id": "openalex:test",
                "title": "Example HEA catalyst paper",
                "doi": "10.1000/example",
                "review_status": "accepted",
                "assertions": [{
                    "kind": "element_set",
                    "value": ["Cu", "Al", "Fe", "Co", "Ni"],
                    "evidence_level": "explicit",
                    "inferred": False,
                }],
            }],
        )

        self.base_candidate = {
            "candidate_id": "candidate-base",
            "composition": {
                "Cu": 8,
                "Al": 3,
                "Fe": 7,
                "Co": 7,
                "Ni": 7,
            },
        }

    def test_returns_all_six_score_dimensions(self):
        result = self.evaluator.evaluate(
            self.base_candidate,
            self.constraints,
        )

        self.assertEqual(
            set(result["scores"]),
            set(DEFAULT_WEIGHTS),
        )
        self.assertEqual(result["schema_version"], "c2.0")

    def test_atomic_fractions_sum_to_one(self):
        result = self.evaluator.evaluate(
            self.base_candidate,
            self.constraints,
        )

        self.assertAlmostEqual(
            sum(result["atomic_fractions"].values()),
            1.0,
            places=5,
        )
        self.assertAlmostEqual(
            result["atomic_fractions"]["Cu"],
            8 / 32,
            places=5,
        )

    def test_exact_literature_element_set_scores_100(self):
        result = self.evaluator.evaluate(
            self.base_candidate,
            self.constraints,
        )

        self.assertEqual(
            result["scores"]["literature_support"],
            100.0,
        )
        best = result["details"]["literature_support"][
            "best_evidence"
        ]
        self.assertEqual(best["evidence_id"], "E1")

    def test_no_preference_uses_neutral_score(self):
        constraints = CandidateConstraintBuilder().build(
            {
                "reaction_id": "CO2RR_CO",
                "reaction_family": "CO2RR",
                "target_product": "CO",
            }
        )

        result = self.evaluator.evaluate(
            self.base_candidate,
            constraints,
        )

        self.assertEqual(
            result["scores"]["constraint_preference"],
            50.0,
        )

    def test_total_score_matches_weighted_sum(self):
        result = self.evaluator.evaluate(
            self.base_candidate,
            self.constraints,
        )

        expected = sum(
            result["scores"][name] * weight
            for name, weight in DEFAULT_WEIGHTS.items()
        )

        self.assertAlmostEqual(
            result["total_score"],
            expected,
            places=5,
        )

    def test_c2_never_eliminates_candidate(self):
        result = self.evaluator.evaluate(
            {
                "candidate_id": "precious-candidate",
                "composition": {
                    "Au": 7,
                    "Ag": 7,
                    "Pt": 6,
                    "Pd": 6,
                    "Ge": 6,
                },
            },
            self.constraints,
        )

        self.assertTrue(result["ranking_only"])
        self.assertFalse(result["eliminated"])
        self.assertEqual(
            result["decision"],
            "scored_not_filtered",
        )

    def test_abundant_candidate_has_better_resource_scores(self):
        abundant = {
            "candidate_id": "abundant",
            "composition": {
                "Al": 7,
                "Fe": 7,
                "Ti": 6,
                "Mn": 6,
                "Cr": 6,
            },
        }
        precious = {
            "candidate_id": "precious",
            "composition": {
                "Au": 7,
                "Ag": 7,
                "Pt": 6,
                "Pd": 6,
                "Ge": 6,
            },
        }

        abundant_result = self.evaluator.evaluate(
            abundant,
            self.constraints,
        )
        precious_result = self.evaluator.evaluate(
            precious,
            self.constraints,
        )

        self.assertGreater(
            abundant_result["scores"]["element_abundance"],
            precious_result["scores"]["element_abundance"],
        )
        self.assertGreater(
            abundant_result["scores"]["price"],
            precious_result["scores"]["price"],
        )

    def test_evaluate_many_returns_all_candidates_ranked(self):
        candidates = [
            self.base_candidate,
            {
                "candidate_id": "candidate-precious",
                "composition": {
                    "Au": 7,
                    "Ag": 7,
                    "Pt": 6,
                    "Pd": 6,
                    "Ge": 6,
                },
            },
        ]

        results = self.evaluator.evaluate_many(
            candidates,
            self.constraints,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(
            [result["rank"] for result in results],
            [1, 2],
        )
        self.assertGreaterEqual(
            results[0]["total_score"],
            results[1]["total_score"],
        )
        self.assertTrue(
            all(not result["eliminated"] for result in results)
        )

    def test_unknown_element_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "Unsupported candidate element",
        ):
            self.evaluator.evaluate(
                {
                    "composition": {
                        "Cu": 8,
                        "Fe": 6,
                        "Co": 6,
                        "Ni": 6,
                        "Hg": 6,
                    },
                },
                self.constraints,
            )

    def test_non_32_atom_composition_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "32-atom",
        ):
            self.evaluator.evaluate(
                {
                    "composition": {
                        "Cu": 5,
                        "Fe": 5,
                        "Co": 5,
                        "Ni": 5,
                        "Mn": 5,
                    },
                },
                self.constraints,
            )


if __name__ == "__main__":
    unittest.main()