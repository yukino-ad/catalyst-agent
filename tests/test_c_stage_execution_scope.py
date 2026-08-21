import unittest
from unittest.mock import patch

from app.domain.task_context import TaskContextBuilder
from app.graph import nodes
from app.graph.routes import (
    route_after_c7_dft_upgrade_review,
    route_after_c_stage_execution_review,
    route_after_formation_energy,
    route_after_stability_screening,
    route_after_structure_modeling,
)


class ExplicitActionIntentTest(unittest.TestCase):
    def setUp(self):
        self.builder = TaskContextBuilder()
        self.llm_overreach = {
            "reaction_id": "CO2RR_GENERAL",
            "reaction_family": "CO2RR",
            "target_product": None,
            "material_family": "high_entropy_alloy",
            "needs_candidate_design": True,
            "needs_structure_modeling": True,
            "needs_property_prediction": True,
            "needs_dft": True,
        }

    def test_design_request_does_not_inherit_llm_downstream_actions(self):
        context, _ = self.builder.build(
            "给我设计一个用于二氧化碳还原的高熵催化剂",
            self.llm_overreach,
        )

        self.assertFalse(context["needs_structure_modeling"])
        self.assertFalse(context["needs_property_prediction"])
        self.assertFalse(context["needs_dft"])
        self.assertEqual(context["requested_scope"], "candidate_only")

    def test_explicit_downstream_actions_are_recorded(self):
        context, _ = self.builder.build(
            "设计HER高熵合金，并进行FCC建模、性质预测和DFT计算",
            self.llm_overreach,
        )

        self.assertTrue(context["needs_structure_modeling"])
        self.assertTrue(context["needs_property_prediction"])
        self.assertTrue(context["needs_dft"])
        self.assertEqual(context["requested_scope"], "full_workflow")


class CStageExecutionReviewTest(unittest.TestCase):
    @patch(
        "app.graph.nodes.interrupt",
        return_value={"mode": "stability_screening", "note": "approve"},
    )
    def test_review_records_explicit_boundary(self, mocked_interrupt):
        result = nodes.c_stage_execution_review_node({
            "selected_candidates": [{"candidate_id": "C1"}],
        })

        request = mocked_interrupt.call_args.args[0]
        self.assertEqual(request["type"], "c_stage_execution_review_required")
        self.assertEqual(request["recommended_mode"], "stability_screening")
        self.assertEqual(result["c_stage_execution_mode"], "stability_screening")

    def test_no_selection_stops_without_interrupt(self):
        with patch("app.graph.nodes.interrupt") as mocked_interrupt:
            result = nodes.c_stage_execution_review_node({
                "selected_candidates": [],
            })

        mocked_interrupt.assert_not_called()
        self.assertEqual(result["c_stage_execution_mode"], "candidate_only")

    def test_routes_stop_at_user_approved_boundaries(self):
        self.assertEqual(
            route_after_c_stage_execution_review({
                "c_stage_execution_mode": "candidate_only",
            }),
            "end",
        )
        self.assertEqual(
            route_after_structure_modeling({
                "c_stage_execution_mode": "fcc_only",
            }),
            "end",
        )
        self.assertEqual(
            route_after_stability_screening({
                "c_stage_execution_mode": "stability_screening",
                "slab_eligible_structures": [{"structure_id": "S1"}],
            }),
            "review",
        )
        self.assertEqual(
            route_after_stability_screening({
                "c_stage_execution_mode": "dft_validation",
                "slab_eligible_structures": [{"structure_id": "S1"}],
            }),
            "slab",
        )
        self.assertEqual(
            route_after_stability_screening({
                "c_stage_execution_mode": "stability_screening",
                "slab_eligible_structures": [],
            }),
            "end",
        )

    @patch(
        "app.graph.nodes.interrupt",
        return_value={
            "select": ["S2"],
            "reject": ["S1"],
            "defer": [],
            "note": "continue one structure",
        },
    )
    def test_c7_review_forwards_only_selected_passed_structure(
        self,
        mocked_interrupt,
    ):
        result = nodes.c7_dft_upgrade_review_node({
            "slab_eligible_structures": [
                {
                    "structure_id": "S1",
                    "candidate_id": "C1",
                    "formation_energy": 0.039,
                },
                {
                    "structure_id": "S2",
                    "candidate_id": "C2",
                    "formation_energy": 0.042,
                },
            ],
        })

        request = mocked_interrupt.call_args.args[0]
        self.assertEqual(request["type"], "c7_dft_upgrade_review_required")
        self.assertEqual(
            request["structures"][1]["formation_energy_ev_per_atom"],
            0.042,
        )
        self.assertEqual(result["c_stage_execution_mode"], "dft_validation")
        self.assertEqual(
            [item["structure_id"] for item in result["slab_eligible_structures"]],
            ["S2"],
        )
        self.assertEqual(route_after_c7_dft_upgrade_review(result), "slab")

    @patch(
        "app.graph.nodes.interrupt",
        return_value={"select": [], "defer": ["S1"]},
    )
    def test_c7_review_stops_when_no_structure_is_selected(
        self,
        mocked_interrupt,
    ):
        result = nodes.c7_dft_upgrade_review_node({
            "slab_eligible_structures": [{"structure_id": "S1"}],
        })

        self.assertEqual(result["slab_eligible_structures"], [])
        self.assertEqual(route_after_c7_dft_upgrade_review(result), "end")

    def test_conditional_online_and_modeling_negation_are_canonical(self):
        context, _ = TaskContextBuilder().build(
            "设计高熵合金，仅在本地证据不足时进行少量联网补充，"
            "本次不继续结构建模。",
            {
                "reaction_id": "CO2RR_GENERAL",
                "material_family": "high_entropy_alloy",
                "needs_candidate_design": True,
                "needs_structure_modeling": True,
                "needs_property_prediction": True,
                "needs_dft": True,
            },
        )

        self.assertEqual(context["online_preference"], "auto")
        self.assertFalse(context["needs_structure_modeling"])

    def test_property_mode_never_routes_domain_gap_to_bulk_dft(self):
        state = {
            "c_stage_execution_mode": "stability_screening",
            "dft_formation_energy_queue": [{"structure_id": "S1"}],
        }
        self.assertEqual(route_after_formation_energy(state), "stability")


if __name__ == "__main__":
    unittest.main()
