import unittest

from app.domain.reaction_profiles import detect_reaction_profile
from app.domain.task_context import TaskContextBuilder


class TaskContextBuilderTest(unittest.TestCase):
    def setUp(self):
        self.builder = TaskContextBuilder()

    @staticmethod
    def analysis(question: str) -> dict:
        profile = detect_reaction_profile(question)
        return {
            "reaction_id": profile["reaction_id"],
            "reaction_family": profile["reaction_family"],
            "target_product": profile.get("target_product"),
            "material_family": "high_entropy_alloy",
            "needs_candidate_design": True,
            "needs_structure_modeling": False,
            "needs_property_prediction": False,
            "needs_dft": False,
            "reaction_profile": profile,
            "analysis_mode": "rule_fallback",
        }

    def test_explicit_co_task_builds_precise_search_contract(self):
        question = (
            "设计用于CO2还原选择性生成CO的五元FCC高熵合金，"
            "只输出候选，不继续建模"
        )
        context, validation = self.builder.build(
            question,
            self.analysis(question),
        )

        self.assertEqual(context["reaction_id"], "CO2RR_CO")
        self.assertEqual(context["target_product"], "CO")
        self.assertEqual(context["requested_scope"], "candidate_only")
        self.assertFalse(context["needs_structure_modeling"])
        self.assertIn("CO selectivity", context["query_terms"])
        self.assertIn(
            "explicit_five_element_composition",
            context["evidence_requirements"],
        )
        self.assertEqual(validation["status"], "validated")

    def test_general_co2rr_does_not_invent_product(self):
        question = "设计一种用于二氧化碳电还原的高熵合金"
        context, _ = self.builder.build(
            question,
            self.analysis(question),
        )

        self.assertEqual(context["reaction_id"], "CO2RR_GENERAL")
        self.assertIsNone(context["target_product"])
        self.assertIn("target_product", context["unresolved_fields"])
        self.assertNotIn("CO selectivity", context["query_terms"])

    def test_unknown_reaction_requires_clarification(self):
        question = "帮我设计一种五元高熵电催化剂"
        context, _ = self.builder.build(
            question,
            self.analysis(question),
        )

        self.assertEqual(context["reaction_id"], "UNKNOWN")
        self.assertTrue(context["requires_clarification"])
        self.assertIn("reaction_family", context["unresolved_fields"])

    def test_user_online_and_offline_preferences_are_deterministic(self):
        online, _ = self.builder.build(
            "联网检索最新的HER高熵催化剂",
            self.analysis("联网检索最新的HER高熵催化剂"),
        )
        offline, _ = self.builder.build(
            "只用本地文献设计HER高熵催化剂",
            self.analysis("只用本地文献设计HER高熵催化剂"),
        )

        self.assertEqual(online["online_preference"], "required")
        self.assertEqual(offline["online_preference"], "forbidden")

if __name__ == "__main__":
    unittest.main()
