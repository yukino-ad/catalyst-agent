import json
import unittest

from app.domain.candidate_constraints import (
    CandidateConstraintBuilder,
)
from app.domain.candidate_evaluator import (
    CandidateEvaluator,
)
from app.domain.candidate_generation import (
    ConstraintDrivenCandidateGenerator,
)


class ConstraintDrivenCandidateGeneratorTest(
    unittest.TestCase
):
    def setUp(self):
        self.constraint_builder = CandidateConstraintBuilder()
        self.generator = (
            ConstraintDrivenCandidateGenerator(
                self.constraint_builder
            )
        )
        self.task = {
            "reaction_id": "CO2RR_CO",
            "reaction_family": "CO2RR",
            "target_product": "CO",
            "material_family": "high_entropy_alloy",
        }

    def test_default_generation_contains_cu_and_non_cu_candidates(
        self,
    ):
        constraints = self.constraint_builder.build(self.task)

        result = self.generator.generate(
            constraints,
            max_candidates=None,
        )

        self.assertGreater(result["candidate_count"], 0)
        self.assertTrue(
            any(
                candidate["contains_cu"]
                for candidate in result["candidates"]
            )
        )
        self.assertTrue(
            any(
                not candidate["contains_cu"]
                for candidate in result["candidates"]
            )
        )

    def test_required_cu_makes_every_candidate_contain_cu(self):
        constraints = self.constraint_builder.build(
            self.task,
            user_overrides={
                "required_elements": ["Cu"],
            },
        )

        result = self.generator.generate(constraints)

        self.assertGreater(result["candidate_count"], 0)
        self.assertTrue(
            all(
                candidate["contains_cu"]
                for candidate in result["candidates"]
            )
        )

    def test_excluded_cu_removes_cu_from_every_candidate(self):
        constraints = self.constraint_builder.build(
            self.task,
            user_overrides={
                "excluded_elements": ["Cu"],
            },
        )

        result = self.generator.generate(
            constraints,
            max_candidates=50,
        )

        self.assertGreater(result["candidate_count"], 0)
        self.assertTrue(
            all(
                not candidate["contains_cu"]
                for candidate in result["candidates"]
            )
        )

    def test_every_candidate_has_five_elements_and_32_atoms(
        self,
    ):
        constraints = self.constraint_builder.build(self.task)

        result = self.generator.generate(
            constraints,
            max_candidates=200,
        )

        for candidate in result["candidates"]:
            self.assertEqual(
                len(candidate["elements"]),
                5,
            )
            self.assertEqual(
                candidate["total_atoms"],
                32,
            )
            self.assertEqual(
                sum(candidate["composition"].values()),
                32,
            )

    def test_every_candidate_has_at_most_one_p_block_element(
        self,
    ):
        constraints = self.constraint_builder.build(self.task)

        result = self.generator.generate(
            constraints,
            max_candidates=200,
        )

        for candidate in result["candidates"]:
            self.assertLessEqual(
                len(candidate["p_block_elements"]),
                1,
            )

    def test_cu_with_p_block_uses_c1_composition_rule(self):
        constraints = self.constraint_builder.build(
            self.task,
            user_overrides={
                "required_elements": [
                    "Cu", "Al", "Fe", "Co", "Ni",
                ],
            },
        )

        result = self.generator.generate(constraints)
        candidate = result["candidates"][0]

        self.assertEqual(
            candidate["composition"],
            {
                "Cu": 8,
                "Al": 3,
                "Fe": 7,
                "Co": 7,
                "Ni": 7,
            },
        )

    def test_no_cu_with_p_block_uses_c1_composition_rule(
        self,
    ):
        constraints = self.constraint_builder.build(
            self.task,
            user_overrides={
                "required_elements": [
                    "Al", "Fe", "Co", "Ni", "Mn",
                ],
                "excluded_elements": ["Cu"],
            },
        )

        result = self.generator.generate(constraints)
        candidate = result["candidates"][0]

        self.assertEqual(
            candidate["composition"],
            {
                "Al": 4,
                "Fe": 7,
                "Co": 7,
                "Ni": 7,
                "Mn": 7,
            },
        )

    def test_no_cu_no_p_can_generate_multiple_variants(self):
        constraints = self.constraint_builder.build(
            self.task,
            user_overrides={
                "required_elements": [
                    "Fe", "Co", "Ni", "Mn", "Mo",
                ],
                "excluded_elements": ["Cu"],
            },
        )

        result = self.generator.generate(
            constraints,
            variants_per_combination=3,
        )

        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(
            {
                tuple(
                    candidate["composition"].values()
                )
                for candidate in result["candidates"]
            },
            {
                (7, 7, 6, 6, 6),
                (6, 7, 7, 6, 6),
                (6, 6, 7, 7, 6),
            },
        )

    def test_explicit_cu_composition_can_generate_arrangement_variants(self):
        constraints = self.constraint_builder.build(
            self.task,
            user_overrides={
                "required_elements": ["Cu", "Fe", "Co", "Ni", "Mn"],
            },
        )
        result = self.generator.generate(
            constraints,
            variants_per_combination=3,
            fixed_composition_variants=True,
        )
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(
            {candidate["variant_index"] for candidate in result["candidates"]},
            {0, 1, 2},
        )
        self.assertEqual(
            len({candidate["candidate_id"] for candidate in result["candidates"]}),
            3,
        )
        self.assertEqual(
            len({tuple(candidate["composition"].items())
                 for candidate in result["candidates"]}),
            1,
        )

    def test_max_candidates_truncates_but_does_not_filter(
        self,
    ):
        constraints = self.constraint_builder.build(self.task)

        result = self.generator.generate(
            constraints,
            max_candidates=10,
        )

        self.assertEqual(result["candidate_count"], 10)
        self.assertTrue(result["truncated"])
        self.assertTrue(
            all(
                not candidate["eliminated"]
                for candidate in result["candidates"]
            )
        )

    def test_generation_result_is_json_serializable(self):
        constraints = self.constraint_builder.build(self.task)

        result = self.generator.generate(
            constraints,
            max_candidates=10,
        )

        serialized = json.dumps(
            result,
            ensure_ascii=False,
        )

        self.assertIn('"schema_version": "c3.0"', serialized)

    def test_generate_and_score_uses_c2(self):
        constraints = self.constraint_builder.build(
            self.task,
            user_overrides={
                "preferred_elements": ["Cu", "Ni"],
            },
        )

        result = self.generator.generate_and_score(
            constraints=constraints,
            evaluator=CandidateEvaluator(),
            max_candidates=20,
        )

        self.assertTrue(result["scoring_applied"])
        self.assertEqual(result["scoring_stage"], "c2")
        self.assertEqual(len(result["candidates"]), 20)
        self.assertEqual(
            [
                candidate["rank"]
                for candidate in result["candidates"]
            ],
            list(range(1, 21)),
        )
        self.assertTrue(
            all(
                candidate["decision"]
                == "scored_not_filtered"
                for candidate in result["candidates"]
            )
        )

    def test_candidate_ids_are_stable(self):
        constraints = self.constraint_builder.build(self.task)

        first = self.generator.generate(
            constraints,
            max_candidates=20,
        )
        second = self.generator.generate(
            constraints,
            max_candidates=20,
        )

        self.assertEqual(
            [
                candidate["candidate_id"]
                for candidate in first["candidates"]
            ],
            [
                candidate["candidate_id"]
                for candidate in second["candidates"]
            ],
        )

    def test_invalid_variant_count_is_rejected(self):
        constraints = self.constraint_builder.build(self.task)

        with self.assertRaisesRegex(
            ValueError,
            "between 1 and 5",
        ):
            self.generator.generate(
                constraints,
                variants_per_combination=6,
            )


if __name__ == "__main__":
    unittest.main()
