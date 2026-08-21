import json
import unittest
from unittest.mock import Mock

from tools.literature.kimi_crossref_verifier import KimiCrossrefVerifier
from tools.llm_client import LLMError


class KimiAcademicSearchTest(unittest.TestCase):
    def setUp(self):
        self.llm = Mock()
        self.llm.available = True
        self.registry = Mock()
        self.verifier = KimiCrossrefVerifier(self.llm, self.registry)
        self.paper = {
            "paper_id": "crossref:10.1000/test",
            "doi": "10.1000/test",
            "title": "CuFeCoNiMn HEA for CO2RR",
            "year": 2025,
            "abstract": "",
            "metadata_verified": True,
            "metadata_provider": "crossref",
        }

    @staticmethod
    def call(call_id, name):
        return {
            "id": call_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps({"query": "hea co2rr", "limit": 10}),
            },
        }

    def test_both_tools_and_exact_doi_create_cross_verification(self):
        self.llm.chat_with_tools.side_effect = [
            {"content": "", "tool_calls": [self.call("c1", "search_crossref")]},
            {"content": "", "tool_calls": [
                self.call("c2", "search_semantic_scholar")
            ]},
            {"content": '{"candidate_dois":["10.1000/test"]}', "tool_calls": []},
        ]
        self.registry.execute.side_effect = [
            {
                "provider": "crossref",
                "count": 1,
                "papers": [dict(self.paper)],
            },
            {
                "provider": "semantic_scholar",
                "count": 1,
                "papers": [{
                    **self.paper,
                    "abstract": "CuFeCoNiMn high entropy alloy for CO2RR.",
                    "semantic_scholar_id": "S2ID",
                    "citation_count": 8,
                }],
            },
        ]
        result = self.verifier.verify(
            [self.paper], {"reaction_family": "CO2RR"}, "find HEA papers"
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["tool_call_count"], 2)
        self.assertTrue(result["papers"][0]["cross_verified"])
        self.assertTrue(result["papers"][0]["abstract"])

    def test_one_tool_cannot_claim_cross_verification(self):
        self.llm.chat_with_tools.side_effect = [
            {"content": "", "tool_calls": [self.call("c1", "search_crossref")]},
            *[
                {"content": "done", "tool_calls": []}
                for _ in range(self.verifier.MAX_STEPS - 1)
            ],
        ]
        self.registry.execute.return_value = {
            "provider": "crossref",
            "count": 1,
            "papers": [dict(self.paper)],
        }
        result = self.verifier.verify(
            [self.paper], {"reaction_family": "CO2RR"}, "find HEA papers"
        )
        self.assertEqual(result["status"], "required_tools_missing")
        self.assertFalse(result["papers"][0]["cross_verified"])

    def test_transient_kimi_http_500_is_retried(self):
        self.verifier.TRANSIENT_RETRY_DELAYS = (0.0,)
        self.llm.chat_with_tools.side_effect = [
            LLMError("HTTP 500: Internal Server Error"),
            {"content": "", "tool_calls": [self.call("c1", "search_crossref")]},
            {"content": "", "tool_calls": [
                self.call("c2", "search_semantic_scholar")
            ]},
            {"content": "{}", "tool_calls": []},
        ]
        self.registry.execute.side_effect = [
            {
                "provider": "crossref",
                "count": 1,
                "papers": [dict(self.paper)],
            },
            {
                "provider": "semantic_scholar",
                "count": 1,
                "papers": [dict(self.paper)],
            },
        ]

        result = self.verifier.verify(
            [self.paper], {"reaction_family": "CO2RR"}, "find HEA papers"
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.llm.chat_with_tools.call_count, 4)


if __name__ == "__main__":
    unittest.main()
