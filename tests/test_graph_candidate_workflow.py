import unittest

from app.graph.routes import (
    route_after_literature_summary,
    route_after_task_analysis,
)
from app.domain.direct_c_stage import classify_direct_c_stage_request
from app.graph.workflow import build_graph


class GraphCandidateWorkflowTest(unittest.TestCase):
    def test_explicit_five_metal_modeling_request_routes_directly_to_c(self):
        decision = classify_direct_c_stage_request(
            "我要构造一个高熵CuFeNiCoMn催化剂",
            {
                "analysis_mode": "llm",
                "needs_structure_modeling": True,
            },
        )
        self.assertTrue(decision["requested"])
        self.assertFalse(decision["needs_candidate_design"])
        self.assertTrue(decision["fixed_composition_sampling"])
        self.assertEqual(decision["structure_variant_count"], 3)
        self.assertEqual(
            decision["scientific_scope"],
            "reaction_agnostic_bulk_stability",
        )
        self.assertEqual(
            decision["specified_elements"],
            ["Cu", "Fe", "Ni", "Co", "Mn"],
        )
        self.assertEqual(
            route_after_task_analysis({"direct_c_stage": decision}),
            "direct_c",
        )

    def test_literature_request_with_composition_keeps_normal_path(self):
        decision = classify_direct_c_stage_request(
            "请调研CuFeNiCoMn高熵合金文献",
            {"analysis_mode": "llm", "needs_structure_modeling": False},
        )
        self.assertFalse(decision["requested"])
        self.assertEqual(
            route_after_task_analysis({"direct_c_stage": decision}),
            "normal",
        )

    def test_direct_route_requires_exactly_five_supported_elements(self):
        for question in (
            "构造高熵CuFeNiCo催化剂",
            "构造高熵CuFeNiCoMnCr催化剂",
        ):
            decision = classify_direct_c_stage_request(
                question,
                {"analysis_mode": "rule_fallback"},
            )
            self.assertFalse(decision["requested"])

    def test_graph_contains_c_stage_nodes(self):
        graph = build_graph()

        self.assertIn(
            "c_stage_preparation",
            graph.nodes,
        )
        self.assertIn(
            "candidate_generation",
            graph.nodes,
        )
        self.assertIn(
            "candidate_review",
            graph.nodes,
        )
        self.assertIn(
            "formation_energy",
            graph.nodes,
        )

    def test_design_task_enters_candidate_stage(self):
        route = route_after_literature_summary({
            "task_analysis": {
                "needs_candidate_design": True,
            },
            "literature_evidence_contract": {
                "evidence_backed_candidate_ready": True,
            },
        })

        self.assertEqual(
            route,
            "candidate_design",
        )

    def test_literature_only_task_ends(self):
        route = route_after_literature_summary({
            "task_analysis": {
                "needs_candidate_design": False,
            }
        })

        self.assertEqual(route, "end")

    def test_ambiguous_task_ends_before_candidate_generation(self):
        route = route_after_literature_summary({
            "task_analysis": {
                "needs_candidate_design": True,
            },
            "canonical_task_context": {
                "requires_clarification": True,
            },
        })

        self.assertEqual(route, "end")


if __name__ == "__main__":
    unittest.main()
