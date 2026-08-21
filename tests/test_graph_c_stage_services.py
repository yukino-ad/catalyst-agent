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
from app.domain.candidate_review import (
    CandidateReviewGate,
)
from app.graph.services import create_services
from app.graph.state import CatalystState


class GraphCStageServicesTest(unittest.TestCase):
    def setUp(self):
        self.services = create_services()

    def test_state_contains_all_c_stage_fields(self):
        annotations = CatalystState.__annotations__

        expected_fields = {
            "c_stage_capability",
            "candidate_constraints",
            "candidate_generation",
            "candidate_review",
            "selected_candidates",
        }

        self.assertTrue(
            expected_fields <= set(annotations)
        )

    def test_services_register_c1_to_c4(self):
        self.assertIsInstance(
            self.services.candidate_constraint_builder,
            CandidateConstraintBuilder,
        )
        self.assertIsInstance(
            self.services.candidate_evaluator,
            CandidateEvaluator,
        )
        self.assertIsInstance(
            self.services.candidate_generator,
            ConstraintDrivenCandidateGenerator,
        )
        self.assertIsInstance(
            self.services.candidate_review_gate,
            CandidateReviewGate,
        )

    def test_c1_and_c3_share_constraint_builder(self):
        self.assertIs(
            self.services.candidate_generator.constraint_builder,
            self.services.candidate_constraint_builder,
        )

    def test_r1_resolver_is_callable(self):
        self.assertTrue(
            callable(self.services.c_stage_resolver)
        )

        result = self.services.c_stage_resolver(
            {
                "reaction_id": "HER",
                "material_family": "high_entropy_alloy",
            },
            [],
        )

        self.assertTrue(
            result["can_generate_candidates"]
        )
        self.assertEqual(
            result["generation_mode"],
            "exploratory",
        )

    def test_services_can_execute_c1_c3_c2_chain(self):
        constraints = (
            self.services.candidate_constraint_builder.build(
                {
                    "reaction_id": "CO2RR_CO",
                    "reaction_family": "CO2RR",
                    "target_product": "CO",
                    "material_family": "high_entropy_alloy",
                }
            )
        )

        result = (
            self.services.candidate_generator.generate_and_score(
                constraints=constraints,
                evaluator=self.services.candidate_evaluator,
                max_candidates=5,
            )
        )

        self.assertEqual(result["candidate_count"], 5)
        self.assertTrue(result["scoring_applied"])
        self.assertEqual(
            [candidate["rank"] for candidate in result["candidates"]],
            [1, 2, 3, 4, 5],
        )

    def test_services_can_execute_c4_review(self):
        candidates = [
            {
                "candidate_id": "C1",
                "rank": 1,
            },
            {
                "candidate_id": "C2",
                "rank": 2,
            },
        ]

        result = self.services.candidate_review_gate.review(
            candidates=candidates,
            decision={
                "select": ["C1"],
                "defer": ["C2"],
            },
            total_candidate_count=100,
        )

        self.assertEqual(result["selected_count"], 1)
        self.assertTrue(
            result["ready_for_structure_modeling"]
        )

    def test_c_stage_results_are_json_serializable(self):
        capability = self.services.c_stage_resolver(
            {
                "reaction_id": "CO2RR_CO",
                "material_family": "high_entropy_alloy",
            },
            [],
        )

        text = json.dumps(
            capability,
            ensure_ascii=False,
        )

        self.assertIn(
            "c-stage-capability-v1",
            text,
        )


if __name__ == "__main__":
    unittest.main()