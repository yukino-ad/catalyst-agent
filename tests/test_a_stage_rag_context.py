import unittest

from app.domain.reaction_profiles import detect_reaction_profile
from app.domain.task_context import TaskContextBuilder
from app.planner import TaskPlanner
from app.task_router import TaskRouter
from tools.llm_client import LLMSettings, OpenAICompatibleClient


class AStageRAGContextTest(unittest.TestCase):
    def setUp(self):
        self.builder = TaskContextBuilder()
        self.disabled = OpenAICompatibleClient(
            LLMSettings(False, "", "https://example.test/v1", "none", 10)
        )

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

    def test_unknown_reaction_does_not_enter_rag(self):
        question = "帮我设计一种五元高熵电催化剂"
        context, _ = self.builder.build(question, self.analysis(question))

        route = TaskRouter(self.disabled).route(question, context)

        self.assertFalse(route["use_rag"])
        self.assertTrue(route["requires_clarification"])
        self.assertTrue(route["clarification_question"])

    def test_router_and_planner_share_validated_context(self):
        question = "设计CO2还原生成CO的五元高熵合金，只输出候选"
        context, _ = self.builder.build(question, self.analysis(question))

        route = TaskRouter(self.disabled).route(question, context)
        plan = TaskPlanner(self.disabled).plan(question, context)

        self.assertTrue(route["use_rag"])
        self.assertIn("CO selectivity", route["rag_query"])
        self.assertIn("CO selectivity", plan["keywords"])
        self.assertEqual(plan["product"], "CO")


if __name__ == "__main__":
    unittest.main()
