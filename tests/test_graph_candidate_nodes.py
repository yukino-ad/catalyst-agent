import json
import unittest
from unittest.mock import patch

from app.graph import nodes


class GraphCandidateNodesTest(unittest.TestCase):
    def setUp(self):
        self.task = {
            "reaction_id": "HER",
            "reaction_family": "HER",
            "target_product": "H2",
            "material_family": "high_entropy_alloy",
        }

    def test_required_elements_trigger_design_but_not_implicit_modeling(self):
        analysis = {
            **self.task,
            "reaction_profile": {},
            "needs_candidate_design": False,
            "needs_structure_modeling": False,
        }
        with patch.object(
            nodes.services.analyzer,
            "analyze",
            return_value=analysis,
        ):
            result = nodes.task_analysis_node({
                "question": "Run one required composition",
                "candidate_user_overrides": {
                    "required_elements": [
                        "Cu", "Ni", "Fe", "Au", "Co",
                    ],
                },
                "errors": [],
            })

        resolved = result["task_analysis"]
        self.assertTrue(resolved["needs_candidate_design"])
        self.assertFalse(resolved["needs_structure_modeling"])
        self.assertTrue(resolved["structured_candidate_request"])

    def test_preparation_builds_exploratory_constraints(self):
        result = nodes.c_stage_preparation_node({
            "task_analysis": self.task,
            "papers": [],
            "warnings": [],
            "errors": [],
        })

        self.assertEqual(
            result["status"],
            "candidate_constraints_ready",
        )
        self.assertEqual(
            result["c_stage_capability"]["generation_mode"],
            "exploratory",
        )
        self.assertEqual(
            result["candidate_constraints"]["reaction"][
                "reaction_id"
            ],
            "HER",
        )

    def test_preparation_respects_user_overrides(self):
        result = nodes.c_stage_preparation_node({
            "task_analysis": self.task,
            "papers": [],
            "candidate_user_overrides": {
                "required_elements": ["Cu"],
                "excluded_elements": ["Zn"],
            },
            "warnings": [],
            "errors": [],
        })

        space = result["candidate_constraints"][
            "candidate_space"
        ]

        self.assertEqual(
            space["required_elements"],
            ["Cu"],
        )
        self.assertNotIn(
            "Zn",
            space["allowed_elements"],
        )

    def test_direct_c_uses_user_hypothesis_warning(self):
        result = nodes.c_stage_preparation_node({
            "task_analysis": self.task,
            "direct_c_stage": {
                "requested": True,
                "specified_elements": ["Cu", "Fe", "Ni", "Co", "Mn"],
            },
            "papers": [],
            "candidate_user_overrides": {
                "required_elements": ["Cu", "Fe", "Ni", "Co", "Mn"],
                "required_elements_source": "explicit_direct_c_request",
            },
            "warnings": [],
            "errors": [],
        })
        warnings = result["candidate_constraints"]["warnings"]
        self.assertEqual(
            warnings,
            ["该五元组成由用户明确指定，作为理想建模假设进入 C 阶段。"],
        )
        self.assertNotIn("人工接受的论文中暂未找到", " ".join(warnings))

    def test_oer_without_evidence_skips_c_stage(self):
        result = nodes.c_stage_preparation_node({
            "task_analysis": {
                "reaction_id": "OER",
                "reaction_family": "OER",
                "target_product": "O2",
                "material_family": "high_entropy_alloy",
            },
            "papers": [],
            "warnings": [],
            "errors": [],
        })

        self.assertEqual(
            result["status"],
            "c_stage_skipped",
        )
        self.assertFalse(
            result["c_stage_capability"][
                "can_generate_candidates"
            ]
        )
        self.assertEqual(
            result["selected_candidates"],
            [],
        )

    def test_generation_node_generates_and_scores(self):
        preparation = nodes.c_stage_preparation_node({
            "task_analysis": self.task,
            "papers": [],
            "candidate_user_overrides": {
                "required_elements": [
                    "Cu", "Fe", "Co", "Ni", "Mn",
                ],
            },
            "warnings": [],
            "errors": [],
        })

        result = nodes.candidate_generation_node({
            **preparation,
            "warnings": preparation.get("warnings", []),
            "errors": [],
        })

        generation = result["candidate_generation"]

        self.assertEqual(
            result["status"],
            "candidate_generation_completed",
        )
        self.assertEqual(
            generation["candidate_count"],
            1,
        )
        self.assertTrue(
            generation["scoring_applied"]
        )
        self.assertEqual(
            generation["candidates"][0]["rank"],
            1,
        )

    def test_direct_c_generation_creates_three_arrangement_candidates(self):
        preparation = nodes.c_stage_preparation_node({
            "task_analysis": self.task,
            "direct_c_stage": {
                "requested": True,
                "specified_elements": ["Cu", "Fe", "Ni", "Co", "Mn"],
            },
            "papers": [],
            "candidate_user_overrides": {
                "required_elements": ["Cu", "Fe", "Ni", "Co", "Mn"],
                "required_elements_source": "explicit_direct_c_request",
            },
            "warnings": [],
            "errors": [],
        })
        result = nodes.candidate_generation_node({
            **preparation,
            "direct_c_stage": {"requested": True},
            "warnings": preparation.get("warnings", []),
            "errors": [],
        })
        generation = result["candidate_generation"]
        self.assertEqual(generation["candidate_count"], 3)
        self.assertEqual(
            generation["candidate_variant_mode"],
            "three_deterministic_atomic_arrangements",
        )

    def test_generation_skips_when_capability_denies(self):
        result = nodes.candidate_generation_node({
            "c_stage_capability": {
                "can_generate_candidates": False,
                "reason": "waiting for evidence",
            },
            "candidate_constraints": {},
        })

        self.assertEqual(
            result["status"],
            "candidate_generation_skipped",
        )
        self.assertEqual(
            result["candidate_generation"][
                "candidate_count"
            ],
            0,
        )

    @patch(
        "app.graph.nodes.interrupt",
        return_value={
            "select": ["C1"],
            "reject": ["C2"],
            "defer": [],
            "note": "Select the first candidate.",
        },
    )
    def test_review_node_selects_candidate(
        self,
        mocked_interrupt,
    ):
        candidates = [
            {
                "candidate_id": "C1",
                "rank": 1,
                "elements": ["Cu", "Fe", "Co", "Ni", "Mn"],
                "composition": {
                    "Cu": 8,
                    "Fe": 6,
                    "Co": 6,
                    "Ni": 6,
                    "Mn": 6,
                },
                "total_score": 80.0,
                "scores": {},
                "details": {},
            },
            {
                "candidate_id": "C2",
                "rank": 2,
                "elements": ["Fe", "Co", "Ni", "Mn", "Mo"],
                "composition": {
                    "Fe": 7,
                    "Co": 7,
                    "Ni": 6,
                    "Mn": 6,
                    "Mo": 6,
                },
                "total_score": 75.0,
                "scores": {},
                "details": {},
            },
        ]

        result = nodes.candidate_review_node({
            "task_id": "test-candidate-review",
            "question": "Design an HER HEA catalyst",
            "c_stage_capability": {
                "generation_mode": "exploratory",
            },
            "candidate_generation": {
                "status": "candidate_generation_completed",
                "candidate_count": 2,
                "candidates": candidates,
            },
            "errors": [],
        })

        mocked_interrupt.assert_called_once()

        request = mocked_interrupt.call_args.args[0]
        self.assertEqual(
            request["type"],
            "candidate_review_required",
        )
        self.assertEqual(
            request["displayed_candidate_count"],
            2,
        )

        self.assertEqual(
            result["status"],
            "candidate_review_completed",
        )
        self.assertEqual(
            result["selected_candidates"][0][
                "candidate_id"
            ],
            "C1",
        )

    def test_review_node_skips_without_candidates(self):
        result = nodes.candidate_review_node({
            "candidate_generation": {
                "status": "candidate_generation_skipped",
                "candidate_count": 0,
                "candidates": [],
            }
        })

        self.assertEqual(
            result["status"],
            "candidate_review_skipped",
        )
        self.assertEqual(
            result["selected_candidates"],
            [],
        )

    def test_node_results_are_json_serializable(self):
        result = nodes.c_stage_preparation_node({
            "task_analysis": self.task,
            "papers": [],
            "warnings": [],
            "errors": [],
        })

        text = json.dumps(
            result,
            ensure_ascii=False,
        )

        self.assertIn(
            "candidate_constraints_ready",
            text,
        )


if __name__ == "__main__":
    unittest.main()
