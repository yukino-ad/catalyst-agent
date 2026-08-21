import json
import unittest

from app.graph.nodes import (
    adsorption_reaction_planning_node,
)


class GraphAdsorptionReactionPlanningTest(
    unittest.TestCase
):
    def test_node_creates_formal_adsorbate_queue(self):
        state = {
            "task_id": "C12-TEST-001",
            "question": (
                "设计用于 CO2 还原生成 CO "
                "的高熵催化剂"
            ),
            "task_analysis": {
                "reaction_id": "CO2RR_CO",
                "reaction_family": "CO2RR",
                "target_product": "CO",
            },
            "reaction_profile": {
                "reaction_id": "CO2RR_CO",
                "reaction_family": "CO2RR",
                "target_product": "CO",
            },
            "warnings": [],
            "errors": [],
        }

        result = (
            adsorption_reaction_planning_node(
                state
            )
        )

        self.assertEqual(
            result["status"],
            "adsorption_intermediate_selection_required",
        )
        self.assertEqual(
            result["planned_adsorbates"],
            [],
        )
        self.assertFalse(
            result[
                "adsorption_reaction_plan"
            ][
                "ready_for_site_generation"
            ]
        )

    def test_node_preserves_literature_suggestion(self):
        state = {
            "task_analysis": {
                "reaction_id": "HER",
                "target_product": "H2",
            },
            "reaction_profile": {
                "reaction_id": "HER",
            },
            "adsorption_literature_suggestions": [
                "OH"
            ],
            "warnings": [],
            "errors": [],
        }

        result = (
            adsorption_reaction_planning_node(
                state
            )
        )

        plan = result[
            "adsorption_reaction_plan"
        ]

        self.assertIn(
            "OH",
            plan["suggested_adsorbates"],
        )
        self.assertNotIn(
            "OH",
            result["planned_adsorbates"],
        )

    def test_unknown_reaction_stops_cleanly(self):
        result = (
            adsorption_reaction_planning_node({
                "task_analysis": {
                    "reaction_id": "UNKNOWN",
                },
                "reaction_profile": {},
                "warnings": [],
                "errors": [],
            })
        )

        self.assertEqual(
            result["status"],
            "adsorption_reaction_unsupported",
        )
        self.assertEqual(
            result["planned_adsorbates"],
            [],
        )

    def test_node_result_is_json_serializable(self):
        result = (
            adsorption_reaction_planning_node({
                "task_analysis": {
                    "reaction_id": "OER",
                    "target_product": "O2",
                },
                "reaction_profile": {
                    "reaction_id": "OER",
                },
                "warnings": [],
                "errors": [],
            })
        )

        json.dumps(
            result,
            ensure_ascii=False,
        )


if __name__ == "__main__":
    unittest.main()
