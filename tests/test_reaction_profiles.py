import unittest

from app.domain.reaction_profiles import detect_reaction_profile


class ReactionProfileTest(unittest.TestCase):
    def test_detects_co2rr_to_co(self):
        profile = detect_reaction_profile(
            "设计用于 CO2 还原生成 CO 的高熵催化剂"
        )
        self.assertEqual(profile["reaction_id"], "CO2RR_CO")
        self.assertEqual(profile["support_level"], "full")

    def test_detects_oer_with_fcc_precursor_model_support(self):
        profile = detect_reaction_profile("设计一种析氧反应催化剂")
        self.assertEqual(profile["reaction_id"], "OER")
        self.assertEqual(profile["support_level"], "full")
        self.assertTrue(profile["tool_support"]["candidate_generation"])
        self.assertTrue(profile["tool_support"]["fcc_bulk_modeling"])
        self.assertTrue(profile["tool_support"]["formation_energy_prediction"])
        self.assertFalse(profile["tool_support"]["reaction_activity_prediction"])

    def test_detects_her(self):
        profile = detect_reaction_profile("筛选高熵合金析氢催化剂")
        self.assertEqual(profile["reaction_id"], "HER")
        self.assertIn("H*", profile["key_intermediates"])

    def test_unknown_task_is_not_falsely_supported(self):
        profile = detect_reaction_profile("帮我整理当前文件")
        self.assertEqual(profile["reaction_id"], "UNKNOWN")
        self.assertEqual(profile["support_level"], "unsupported")


if __name__ == "__main__":
    unittest.main()
