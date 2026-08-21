import unittest

from app.domain.reaction_profiles import (
    get_reaction_profile,
    resolve_c_stage_capability,
)


class CStageCapabilityTest(unittest.TestCase):
    @staticmethod
    def task(reaction_id):
        return {
            "reaction_id": reaction_id,
            "material_family": "high_entropy_alloy",
        }

    @staticmethod
    def accepted_paper():
        return {
            "evidence_id": "E1",
            "review_status": "accepted",
            "title": "Reaction-specific HEA paper",
        }

    def test_all_known_reactions_have_c_stage_capability(self):
        for reaction_id in (
            "CO2RR_CO",
            "CO2RR_HCOOH",
            "CO2RR_GENERAL",
            "HER",
            "OER",
            "ORR",
            "NRR",
            "UNKNOWN",
        ):
            profile = get_reaction_profile(reaction_id)
            self.assertIn("c_stage_capability", profile)

    def test_co2rr_co_allows_exploratory_generation(self):
        result = resolve_c_stage_capability(
            self.task("CO2RR_CO"),
            [],
        )
        self.assertTrue(result["can_generate_candidates"])
        self.assertEqual(result["generation_mode"], "exploratory")

    def test_her_allows_exploratory_generation(self):
        result = resolve_c_stage_capability(self.task("HER"), [])
        self.assertTrue(result["can_generate_candidates"])

    def test_orr_with_evidence_is_evidence_conditioned(self):
        result = resolve_c_stage_capability(
            self.task("ORR"),
            [self.accepted_paper()],
        )
        self.assertTrue(result["can_generate_candidates"])
        self.assertEqual(
            result["generation_mode"],
            "evidence_conditioned",
        )

    def test_oer_allows_exploratory_generation(self):
        result = resolve_c_stage_capability(self.task("OER"), [])
        self.assertTrue(result["can_generate_candidates"])
        self.assertEqual(
            result["generation_mode"],
            "exploratory",
        )

    def test_oer_with_evidence_can_generate(self):
        result = resolve_c_stage_capability(
            self.task("OER"),
            [self.accepted_paper()],
        )
        self.assertTrue(result["can_generate_candidates"])
        self.assertEqual(
            result["generation_mode"],
            "evidence_conditioned",
        )

    def test_non_alloy_material_is_not_sent_to_fcc_generator(self):
        result = resolve_c_stage_capability(
            {
                "reaction_id": "OER",
                "material_family": "high_entropy_oxide",
            },
            [self.accepted_paper()],
        )
        self.assertFalse(result["can_generate_candidates"])
        self.assertEqual(
            result["generation_mode"],
            "material_family_unsupported",
        )

    def test_chinese_high_entropy_alloy_alias_is_supported(self):
        result = resolve_c_stage_capability(
            {
                "reaction_id": "HER",
                "material_family": "高熵合金",
            },
            [],
        )
        self.assertTrue(result["can_generate_candidates"])
        self.assertEqual(
            result["material_family"],
            "high_entropy_alloy",
        )
        self.assertEqual(
            result["material_family_raw"],
            "高熵合金",
        )

    def test_modified_chinese_high_entropy_alloy_alias_is_supported(self):
        result = resolve_c_stage_capability(
            {
                "reaction_id": "CO2RR_CO",
                "material_family": "五元FCC高熵合金",
            },
            [self.accepted_paper()],
        )

        self.assertTrue(result["can_generate_candidates"])
        self.assertEqual(
            result["material_family"],
            "high_entropy_alloy",
        )

    def test_unknown_reaction_is_disabled(self):
        result = resolve_c_stage_capability(
            self.task("UNKNOWN"),
            [self.accepted_paper()],
        )
        self.assertFalse(result["can_generate_candidates"])

    def test_activity_prediction_remains_unsupported(self):
        result = resolve_c_stage_capability(
            self.task("CO2RR_CO"),
            [self.accepted_paper()],
        )
        self.assertFalse(result["reaction_activity_prediction"])

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(TypeError):
            resolve_c_stage_capability([], [])
        with self.assertRaises(TypeError):
            resolve_c_stage_capability(self.task("HER"), {})


if __name__ == "__main__":
    unittest.main()
