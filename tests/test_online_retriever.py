import unittest
from unittest.mock import Mock

from tools.literature.online_retriever import (
    OnlineLiteratureRetriever,
)
from tools.literature.schemas import PaperRecord
from tools.literature.crossref_client import CrossrefRateLimitError


class OnlineLiteratureRetrieverTest(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.retriever = OnlineLiteratureRetriever(
            client=self.client
        )
        self.task = {
            "reaction_family": "CO2RR",
            "target_product": "CO",
        }

    def test_skips_when_b3_does_not_require_online(self):
        result = self.retriever.retrieve(
            policy_result={
                "use_online_search": False,
                "decision": "local_sufficient",
            },
            question="设计 CO2 还原催化剂",
            task_analysis=self.task,
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["warnings"], [])
        self.assertIn("Local evidence satisfied", result["reason"])
        self.client.search.assert_not_called()

    def test_calls_crossref_when_b3_requires_online(self):
        self.client.search.return_value = [
            PaperRecord(
                paper_id="crossref:10.1000/test",
                title="High entropy alloys for CO2 reduction",
                abstract="A test abstract.",
                year=2025,
                doi="10.1000/test",
                source="Crossref",
                metadata_verified=True,
                metadata_provider="crossref",
                claim_evidence_available=True,
            )
        ]

        result = self.retriever.retrieve(
            policy_result={
                "use_online_search": True,
                "decision": "online_required",
            },
            question="设计高熵 CO2 还原催化剂",
            task_analysis=self.task,
            keywords=["high entropy alloy"],
            per_page=5,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(
            result["candidates"][0]["review_status"],
            "pending_review",
        )
        self.assertFalse(
            result["candidates"][0][
                "stored_in_repository"
            ]
        )
        self.assertTrue(result["candidates"][0]["metadata_verified"])
        self.assertEqual(
            result["candidates"][0]["metadata_provider"], "crossref"
        )
        self.assertTrue(
            result["candidates"][0]["claim_evidence_available"]
        )
        self.client.search.assert_called_once()

    def test_unverified_mock_record_is_not_promoted(self):
        self.client.search.return_value = [
            PaperRecord(
                paper_id="mock:1",
                title="Unverified paper",
                abstract="CuFeCoNiMn high entropy alloy for CO2RR to CO.",
                doi="10.1000/unverified",
            )
        ]
        result = self.retriever.retrieve(
            policy_result={"use_online_search": True},
            question="CO2 reduction catalyst",
            task_analysis=self.task,
        )
        self.assertFalse(result["candidates"][0]["metadata_verified"])
        self.assertFalse(
            result["candidates"][0]["claim_evidence_available"]
        )

    def test_query_contains_reaction_and_product(self):
        query = self.retriever.build_query(
            question="设计高熵催化剂",
            task_analysis=self.task,
            keywords=[],
        )

        self.assertIn("high entropy alloy", query)
        self.assertIn("carbon dioxide", query)
        self.assertIn("carbon monoxide", query)

    def test_online_failure_does_not_crash_agent(self):
        self.client.search.side_effect = OSError(
            "network unavailable"
        )

        result = self.retriever.retrieve(
            policy_result={
                "use_online_search": True,
                "decision": "online_required",
            },
            question="CO2 reduction catalyst",
            task_analysis=self.task,
        )

        self.assertEqual(
            result["status"],
            "online_failed",
        )
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["warnings"])

    def test_long_rate_limit_cancels_remaining_queries(self):
        self.client.search.side_effect = CrossrefRateLimitError(35858)
        result = self.retriever.retrieve(
            policy_result={"use_online_search": True, "decision": "online_required"},
            question="CO2 reduction catalyst",
            task_analysis=self.task,
            search_queries=["query one", "query two"],
        )
        self.assertEqual(result["status"], "online_failed")
        self.client.search.assert_called_once()

    def test_invalid_per_page_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "per_page",
        ):
            self.retriever.retrieve(
                policy_result={
                    "use_online_search": True,
                },
                question="CO2 reduction",
                task_analysis=self.task,
                per_page=101,
            )


if __name__ == "__main__":
    unittest.main()
