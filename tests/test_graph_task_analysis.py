import os
import unittest
from unittest.mock import patch
from app.graph import nodes
from app.domain.reaction_profiles import detect_reaction_profile

class GraphTaskAnalysisTest(unittest.TestCase):
    def _run_offline(
        self,
        question: str,
        task_id: str,
    ):
        profile = nodes.services.analyzer._rule_analyze(
            question,
            detect_reaction_profile(question),
        )
        offline_route = {
            "intent": question,
            "use_rag": False,
            "rag_reason": "Unit test runs without external services.",
            "rag_query": "",
            "rag_focus": [],
            "requested_actions": [],
            "router_mode": "test_offline",
        }
        offline_plan = nodes.services.planner._rule_plan(
            question
        )
        empty_local = {
            "selected": [],
            "rejected": [],
        }

        local_sufficient = {
            "use_online_search": False,
            "decision": "local_sufficient",
            "warnings": [],
        }

        online_skipped = {
            "status": "skipped",
            "candidate_count": 0,
            "candidates": [],
            "warnings": [],
        }

        with (
            patch.dict(
                os.environ,
                {"LLM_ENABLED": "false"},
            ),
            patch.object(
                nodes.services.analyzer,
                "analyze",
                return_value=profile,
            ),
            patch.object(
                nodes.services.router,
                "route",
                return_value=offline_route,
            ),
            patch.object(
                nodes.services.planner,
                "plan",
                return_value=offline_plan,
            ),
            patch.object(
                nodes.services.local_retriever,
                "retrieve",
                return_value=empty_local,
            ),
            patch.object(
                nodes.services.online_policy,
                "evaluate",
                return_value=local_sufficient,
            ),
            patch.object(
                nodes.services.online_retriever,
                "retrieve",
                return_value=online_skipped,
            ),
        ):
            from app.graph.workflow import (
                build_graph,
            )

            graph = build_graph()

            return graph.invoke(
                {
                    "task_id": task_id,
                    "question": question,
                    "errors": [],
                    "warnings": [],
                    "retry_count": 0,
                    "status": "created",
                },
                config={
                    "configurable": {
                        "thread_id": task_id,
                    }
                },
            )

    def test_co2rr_to_co_has_full_profile(self):
        result = self._run_offline(
            "设计用于 CO2 还原生成 CO 的高熵催化剂",
            "analysis-co2rr",
        )

        self.assertEqual(
            result["task_analysis"]["reaction_id"],
            "CO2RR_CO",
        )
        self.assertEqual(
            result["reaction_profile"]["target_product"],
            "CO",
        )
        self.assertEqual(
            result["capability"]["support_level"],
            "full",
        )
        self.assertNotIn(
            "candidate_generation",
            result["capability"]["missing_tools"],
        )

    def test_oer_literature_request_remains_supported(self):
        result = self._run_offline(
            "调研高熵材料用于析氧反应的研究进展",
            "analysis-oer",
        )

        self.assertEqual(
            result["task_analysis"]["reaction_id"],
            "OER",
        )
        self.assertEqual(
            result["capability"]["support_level"],
            "full",
        )
        self.assertTrue(
            result["capability"]["can_continue_literature"]
        )

    def test_oer_fcc_precursor_modeling_is_supported(self):
        result = self._run_offline(
            "设计并建立析氧反应高熵氧化物结构",
            "analysis-oer-modeling",
        )

        self.assertNotIn(
            "fcc_bulk_modeling",
            result["capability"]["missing_tools"],
        )
        self.assertTrue(
            result["capability"][
                "can_execute_all_requested_actions"
            ]
        )

    def test_unknown_task_is_not_falsely_supported(self):
        result = self._run_offline(
            "帮我整理桌面上的文件",
            "analysis-unknown",
        )

        self.assertEqual(
            result["task_analysis"]["reaction_id"],
            "UNKNOWN",
        )
        self.assertEqual(
            result["capability"]["support_level"],
            "unsupported",
        )


if __name__ == "__main__":
    unittest.main()
