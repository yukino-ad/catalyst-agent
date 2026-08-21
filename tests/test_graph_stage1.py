import os
import unittest
from unittest.mock import patch

from langgraph.types import Command

from app.graph import nodes


def online_paper() -> dict:
    return {
        "paper_id": "openalex:W_TEST",
        "title": (
            "High entropy alloys for "
            "CO2 reduction to CO"
        ),
        "abstract": (
            "The CuFeCoNiMn high-entropy alloy investigates CO2 "
            "reduction and demonstrates 90% Faradaic efficiency."
        ),
        "year": 2025,
        "journal": "Example Journal",
        "doi": "10.1000/test",
        "url": "",
        "source": "OpenAlex",
        "summary": "",
        "assertions": [],
        "retrieval_origin": "online",
        "review_status": "pending_review",
        "stored_in_repository": False,
    }


class GraphStage1Test(unittest.TestCase):
    def test_graph_interrupts_for_literature_review(self):
        local_result = {
            "selected": [],
            "rejected": [],
        }

        policy_result = {
            "use_online_search": True,
            "decision": "online_required",
            "warnings": [],
        }

        online_result = {
            "status": "completed",
            "candidate_count": 1,
            "candidates": [online_paper()],
            "warnings": [],
        }

        verified_paper = {
            **online_paper(),
            "metadata_verified": True,
            "metadata_provider": "crossref",
            "claim_evidence_available": True,
            "cross_verified": True,
            "kimi_cross_verified": True,
        }
        verification_result = {
            "schema_version": "kimi-academic-tools-v1",
            "status": "completed",
            "required_tools_called": True,
            "tool_call_count": 2,
            "mutually_verified_count": 1,
            "papers": [verified_paper],
            "warnings": [],
        }

        commit_result = {
            "status": "commit_completed",
            "database_count_before": 9,
            "database_count_after": 10,
            "stored_count": 1,
            "skipped_count": 0,
            "error_count": 0,
            "stored": [
                {
                    "evidence_id": "E1",
                    "paper_id": "openalex:W_TEST",
                    "title": (
                        "High entropy alloys for "
                        "CO2 reduction to CO"
                    ),
                }
            ],
            "skipped": [],
            "errors": [],
        }

        with (
            patch.dict(
                os.environ,
                {"LLM_ENABLED": "false"},
            ),
            patch.object(
                nodes.services.local_retriever,
                "retrieve",
                return_value=local_result,
            ),
            patch.object(
                nodes.services.online_policy,
                "evaluate",
                return_value=policy_result,
            ),
            patch.object(
                nodes.services.online_retriever,
                "retrieve",
                return_value=online_result,
            ),
            patch.object(
                nodes.services.kimi_crossref_verifier,
                "verify",
                return_value=verification_result,
            ),
            patch.object(
                nodes.services.review_gate,
                "commit_accepted",
                return_value=commit_result,
            ),
            patch.object(
                nodes.services.rag,
                "answer",
                return_value={
                    "answer": "人工接受后的测试总结 [E1]",
                    "citations": ["E1"],
                    "mode": "test",
                },
            ),
        ):
            from app.graph.workflow import (
                build_graph,
            )

            graph = build_graph()

            config = {
                "configurable": {
                    "thread_id": (
                        "test-literature-review"
                    ),
                }
            }

            first_result = graph.invoke(
                {
                    "task_id": (
                        "test-literature-review"
                    ),
                    "question": (
                        "调研用于 CO2 还原生成 CO "
                        "的高熵催化剂文献"
                    ),
                    "errors": [],
                    "warnings": [],
                    "retry_count": 0,
                    "status": "created",
                },
                config=config,
            )

            self.assertIn(
                "__interrupt__",
                first_result,
            )

            interrupt_value = (
                first_result[
                    "__interrupt__"
                ][0].value
            )

            self.assertEqual(
                interrupt_value["type"],
                "literature_review_required",
            )

            self.assertEqual(
                len(
                    interrupt_value[
                        "candidates"
                    ]
                ),
                1,
            )

            self.assertEqual(
                interrupt_value[
                    "candidates"
                ][0]["evidence_id"],
                "E1",
            )

            final_result = graph.invoke(
                Command(
                    resume={
                        "accept": ["E1"],
                        "reject": [],
                        "defer": [],
                        "note": (
                            "测试中接受 E1"
                        ),
                    }
                ),
                config=config,
            )

        self.assertEqual(
            final_result[
                "literature_review"
            ]["status"],
            "review_completed",
        )

        self.assertEqual(
            final_result[
                "literature_review"
            ]["accepted_count"],
            1,
        )

        self.assertEqual(
            final_result["papers"][0][
                "evidence_id"
            ],
            "E1",
        )

        self.assertEqual(
            final_result[
                "literature_commit"
            ]["status"],
            "commit_completed",
        )

        self.assertEqual(
            final_result[
                "literature_commit"
            ]["stored_count"],
            1,
        )

        self.assertNotIn("__interrupt__", final_result)
        self.assertEqual(
            final_result["literature_search_round"],
            3,
        )
        self.assertEqual(final_result["status"], "literature_summarized")
        self.assertFalse(
            final_result["literature_evidence_contract"]
            ["evidence_backed_candidate_ready"]
        )

    def test_graph_can_skip_rag(self):
        with patch.dict(
            os.environ,
            {"LLM_ENABLED": "false"},
        ):
            from app.graph.workflow import (
                build_graph,
            )

            graph = build_graph()

            result = graph.invoke(
                {
                    "task_id": "test-no-rag",
                    "question": (
                        "不检索文献，只打开 OVITO"
                    ),
                    "errors": [],
                    "warnings": [],
                    "retry_count": 0,
                    "status": "created",
                },
                config={
                    "configurable": {
                        "thread_id": (
                            "test-no-rag"
                        ),
                    }
                },
            )

        self.assertFalse(
            result["route"]["use_rag"]
        )

        self.assertNotIn(
            "__interrupt__",
            result,
        )

        self.assertEqual(
            result["rag_result"][
                "synthesis"
            ]["mode"],
            "router_skipped",
        )


if __name__ == "__main__":
    unittest.main()
