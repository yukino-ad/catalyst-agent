import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.planner import TaskPlanner
from app.task_router import TaskRouter
from tools.literature_rag import LiteratureRAG
from tools.llm_client import LLMSettings, OpenAICompatibleClient
from tools.llm_client import LLMError
from tools.literature.openalex_client import restore_abstract
from tools.literature.repository import LiteratureRepository
from tools.literature.schemas import Assertion, Evidence, PaperRecord


class FakeLLM(OpenAICompatibleClient):
    @property
    def available(self) -> bool:
        return True

    def chat_json(self, messages):
        return {
            "reaction": "CO2 reduction reaction",
            "product": "CO",
            "objective": "screen HEA catalysts",
            "constraints": ["FCC"],
            "keywords": ["CO2RR", "high entropy alloy", "COOH intermediate"],
            "required_evidence": ["element rationale"],
            "steps": ["retrieve literature", "build structures"],
        }


class CapturingLLM(OpenAICompatibleClient):
    def __init__(self):
        self.messages = []

    @property
    def available(self) -> bool:
        return True

    def chat(self, messages, temperature=0.2, max_tokens=1800):
        self.messages = messages
        return "Evidence [E1]"


class RoutingLLM(OpenAICompatibleClient):
    @property
    def available(self) -> bool:
        return True

    def chat_json(self, messages):
        return {
            "intent": "design a CO2RR catalyst",
            "use_rag": True,
            "rag_reason": "candidate selection needs literature evidence",
            "rag_query": "high entropy alloy CO2RR to CO",
            "rag_focus": ["COOH adsorption", "CO selectivity"],
            "requested_actions": ["retrieve", "build"],
        }


class LLMRAGTest(unittest.TestCase):
    def test_llm_router_can_enable_rag(self):
        route = TaskRouter(RoutingLLM()).route("design catalyst")
        self.assertTrue(route["use_rag"])
        self.assertEqual(route["router_mode"], "llm")
        self.assertIn("COOH adsorption", route["rag_focus"])

    def test_rule_router_respects_explicit_no_rag_request(self):
        disabled = OpenAICompatibleClient(
            LLMSettings(False, "", "https://example.test/v1", "none", 10)
        )
        route = TaskRouter(disabled).route("不检索文献，只打开 OVITO")
        self.assertFalse(route["use_rag"])
        self.assertEqual(route["router_mode"], "rule_fallback")

    def test_rag_prompt_includes_title_doi_and_abstract(self):
        llm = CapturingLLM()
        rag = LiteratureRAG(llm=llm)
        result = rag._llm_answer("question", {"objective": "objective"}, [{
            "evidence_id": "E1", "title": "Paper title", "year": 2025,
            "doi": "https://doi.org/10.1/example", "url": "https://example.test",
            "abstract": "Verbatim abstract.", "elements": ["Cu"],
            "adsorbates": ["COOH*"], "insights": ["Evidence quote"],
        }])
        prompt = llm.messages[1]["content"]
        self.assertIn("Paper title", prompt)
        self.assertIn("10.1/example", prompt)
        self.assertIn("Verbatim abstract.", prompt)
        self.assertIn("Paper title", result["answer"])
        self.assertIn("10.1/example", result["answer"])
        self.assertIn("摘要原文: Verbatim abstract.", result["answer"])

    def test_assertion_accepts_string_evidence(self):
        assertion = Assertion.from_dict(
            {
                "kind": "reaction",
                "value": "CO2RR",
                "evidence_level": "explicit",
                "confidence": "high",
                "inferred": False,
                "evidence": [
                    "High-entropy alloy catalysts enable CO2 reduction."
                ],
            }
        )

        self.assertEqual(len(assertion.evidence), 1)
        self.assertEqual(
            assertion.evidence[0].quote,
            "High-entropy alloy catalysts enable CO2 reduction.",
        )
        self.assertEqual(assertion.evidence[0].source, "abstract")

    def test_placeholder_api_key_is_rejected_cleanly(self):
        settings = LLMSettings(True, "你的_API_Key", "https://example.test/v1", "model", 10)
        with self.assertRaisesRegex(LLMError, "占位符"):
            settings.validate()

    def test_openalex_abstract_is_restored_in_position_order(self):
        self.assertEqual(restore_abstract({"CO2": [0], "reduction": [1], "works": [2]}), "CO2 reduction works")

    def test_sqlite_repository_upserts_and_searches_structured_records(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = LiteratureRepository(Path(directory) / "literature.db")
            repository.upsert(PaperRecord(
                paper_id="test:1", title="CuAg catalyst for CO2 reduction", abstract="COOH is observed.",
                year=2025, summary="CO2RR to CO", assertions=[
                    Assertion("reaction", "CO2RR", "explicit", "high", [Evidence("CO2 reduction", "title")]),
                    Assertion("product", "CO", "explicit", "high", []),
                    Assertion("element_set", ["Cu", "Ag"], "explicit", "high", []),
                ]
            ))
            hits = repository.search("CO2RR Cu", {"reaction": "CO2RR", "product": "CO"})
            self.assertEqual(repository.count(), 1)
            self.assertEqual(hits[0]["paper_id"], "test:1")

    def test_settings_read_environment_without_exposing_key(self):
        with patch.dict(
            os.environ,
            {
                "LLM_ENABLED": "true",
                "LLM_API_KEY": "secret-test-key",
                "LLM_BASE_URL": "https://example.test/v1",
                "LLM_MODEL": "test-model",
            },
            clear=False,
        ):
            settings = LLMSettings.load()
        self.assertTrue(settings.ready)
        self.assertEqual(settings.model, "test-model")

    def test_llm_planner_validates_structured_result(self):
        plan = TaskPlanner(FakeLLM()).plan("design CO catalyst")
        self.assertEqual(plan["planner_mode"], "llm")
        self.assertEqual(plan["product"], "CO")
        self.assertTrue(plan["keywords"])

    def test_local_rag_returns_traceable_evidence_offline(self):
        disabled = OpenAICompatibleClient(
            LLMSettings(False, "", "https://example.test/v1", "none", 10)
        )
        plan = TaskPlanner(disabled).plan("CO2 reduction to CO")
        with tempfile.TemporaryDirectory() as directory:
            result = LiteratureRAG(llm=disabled, db_path=Path(directory) / "empty.db").run("CO2 reduction to CO", plan)
        self.assertTrue(result["evidence"])
        self.assertEqual(result["synthesis"]["mode"], "extractive_fallback")
        self.assertTrue(all(item["evidence_id"].startswith("E") for item in result["evidence"]))


if __name__ == "__main__":
    unittest.main()
