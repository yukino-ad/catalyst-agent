import json
import unittest

from app.domain.adsorption_reaction_planner import (
    AdsorptionReactionPlanner,
)


class AdsorptionReactionPlannerTest(
    unittest.TestCase
):
    def setUp(self):
        self.planner = AdsorptionReactionPlanner()

    def test_co2rr_co_plan_contains_pathway_and_her(self):
        result = self.planner.plan(
            {
                "reaction_id": "CO2RR_CO",
                "target_product": "CO",
            },
            {
                "reaction_id": "CO2RR_CO",
                "reaction_family": "CO2RR",
                "target_product": "CO",
            },
        )

        self.assertEqual(
            result["status"],
            "adsorption_intermediate_selection_required",
        )
        self.assertEqual(
            result["primary_adsorbates"],
            ["COOH", "CO"],
        )
        self.assertIn(
            "H",
            result["competitive_adsorbates"],
        )
        self.assertEqual(
            result["formal_adsorbates"],
            ["COOH", "CO", "H"],
        )
        self.assertFalse(
            result["ready_for_site_generation"]
        )
        self.assertIsNone(result["selected_adsorbate"])
        self.assertEqual(
            result["reference_energy_definitions"]["CO"][
                "reference_expression"
            ],
            "E_CO",
        )
        self.assertFalse(
            result["activity_prediction_performed"]
        )
        self.assertFalse(
            result["structure_generation_performed"]
        )

    def test_her_only_requires_hydrogen(self):
        result = self.planner.plan({
            "reaction_id": "HER",
            "target_product": "H2",
        })

        self.assertEqual(
            result["formal_adsorbates"],
            ["H"],
        )

    def test_unknown_reaction_does_not_reuse_co2rr(self):
        result = self.planner.plan({
            "reaction_id": "UNKNOWN",
        })

        self.assertEqual(
            result["status"],
            "adsorption_reaction_unsupported",
        )
        self.assertEqual(
            result["formal_adsorbates"],
            [],
        )
        self.assertFalse(
            result["ready_for_site_generation"]
        )

    def test_user_can_require_an_adsorbate(self):
        result = self.planner.plan(
            {
                "reaction_id": "HER",
                "target_product": "H2",
            },
            user_overrides={
                "required_adsorbates": ["OH"],
            },
        )

        self.assertEqual(
            result["formal_adsorbates"],
            ["H", "OH"],
        )

        source = {
            item["adsorbate"]: item
            for item in result["adsorbate_sources"]
        }

        self.assertEqual(
            source["OH"]["source"],
            "user_override",
        )

    def test_user_can_exclude_an_adsorbate(self):
        result = self.planner.plan(
            {
                "reaction_id": "CO2RR_CO",
                "target_product": "CO",
            },
            user_overrides={
                "excluded_adsorbates": ["H"],
            },
        )

        self.assertEqual(
            result["formal_adsorbates"],
            ["COOH", "CO"],
        )

    def test_literature_suggestion_is_not_formal(self):
        result = self.planner.plan(
            {
                "reaction_id": "CO2RR_CO",
                "target_product": "CO",
            },
            literature_suggestions=["CHO"],
        )

        self.assertIn(
            "CHO",
            result["suggested_adsorbates"],
        )
        self.assertNotIn(
            "CHO",
            result["formal_adsorbates"],
        )

        source = {
            item["adsorbate"]: item
            for item in result["adsorbate_sources"]
        }

        self.assertFalse(
            source["CHO"][
                "approved_for_site_generation"
            ]
        )

    def test_general_co2rr_waits_for_target_review(self):
        result = self.planner.plan({
            "reaction_id": "CO2RR_GENERAL",
            "target_product": None,
        })

        self.assertEqual(
            result["formal_adsorbates"],
            ["H"],
        )
        self.assertIn(
            "COOH",
            result["suggested_adsorbates"],
        )
        self.assertEqual(
            result["support_level"],
            "human_review_required",
        )

    def test_result_is_json_serializable(self):
        result = self.planner.plan({
            "reaction_id": "OER",
            "target_product": "O2",
        })

        json.dumps(
            result,
            ensure_ascii=False,
        )


if __name__ == "__main__":
    unittest.main()
