import csv
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from tools.literature.extraction_service import LiteratureAssertionExtractionService
from tools.literature.extractor import LiteratureExtractor
from tools.literature.journal_metrics import JournalMetricRegistry
from tools.literature.review_gate import LiteratureReviewGate
from tools.llm_client import LLMSettings, OpenAICompatibleClient
from app.graph import nodes


def disabled_extractor() -> LiteratureExtractor:
    return LiteratureExtractor(OpenAICompatibleClient(LLMSettings(
        enabled=False, api_key="", base_url="https://example.invalid/v1",
        model="", timeout_seconds=1,
    )))


class B1PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.metric_path = root / "journal_metrics.csv"
        with self.metric_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=JournalMetricRegistry.FIELDNAMES)
            writer.writeheader()
            writer.writerow({
                "journal_name": "Example Journal",
                "issn": "1234-5678",
                "openalex_source_id": "S1",
                "metric_name": "JIF",
                "metric_value": "12.0",
                "metric_year": "2024",
                "source": "JCR",
                "verified_at": "2026-07-24",
            })
        self.service = LiteratureAssertionExtractionService(
            extractor=disabled_extractor(),
            metrics=JournalMetricRegistry(self.metric_path),
            cache_dir=root / "cache",
        )
        self.paper = {
            "evidence_id": "E1",
            "paper_id": "crossref:10.1000/test",
            "title": "CuFeCoNiMn high-entropy alloy for CO2 reduction to CO",
            "abstract": (
                "The CuFeCoNiMn high-entropy alloy demonstrates selective CO "
                "production with a Faradaic efficiency of 92%."
            ),
            "year": 2025,
            "journal": "Example Journal",
            "doi": "10.1000/test",
            "source": "Crossref",
            "metadata_verified": True,
            "metadata_provider": "crossref",
            "claim_evidence_available": True,
            "cross_verified": True,
            "kimi_cross_verified": True,
            "publication_type": "article",
            "issns": ["1234-5678"],
            "retrieval_origin": "online",
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_final_scoring_uses_extracted_assertions_and_verified_metric(self):
        result = self.service.process([self.paper], {
            "reaction_family": "CO2RR", "target_product": "CO",
            "material_family": "high_entropy_alloy",
        })
        paper = result["papers"][0]
        kinds = {item["kind"] for item in paper["assertions"]}
        self.assertIn("element_set", kinds)
        self.assertIn("material_family", kinds)
        self.assertEqual(paper["evidence_quality"]["evaluation_phase"], "final")
        self.assertEqual(paper["evidence_quality"]["journal_impact"]["score"], 16.0)
        self.assertEqual(result["journal_metric_coverage_count"], 1)
        self.assertEqual(result["journal_metric_missing_count"], 0)
        self.assertTrue(any(
            assertion["kind"] == "reaction"
            and assertion["value"] == "CO2RR"
            for assertion in paper["assertions"]
        ))

    def test_second_run_uses_cache(self):
        self.service.process([self.paper], {})
        result = self.service.process([self.paper], {})
        self.assertEqual(result["cache_hit_count"], 1)

    def test_cached_papers_keep_current_run_evidence_ids(self):
        first = dict(self.paper)
        first["evidence_id"] = "E2"
        self.service.process([first], {})

        second = dict(self.paper)
        second["evidence_id"] = "E7"
        result = self.service.process([second], {})

        paper = result["papers"][0]
        self.assertEqual(paper["evidence_id"], "E7")
        self.assertTrue(all(
            assertion["assertion_id"].startswith("E7::")
            for assertion in paper["assertions"]
        ))

    def test_llm_deep_extraction_is_limited_to_five_papers(self):
        papers = []
        for index in range(8):
            item = dict(self.paper)
            item["paper_id"] = f"openalex:W{index}"
            item["doi"] = f"10.1000/{index}"
            papers.append(item)
        result = self.service.process(papers, {})
        self.assertEqual(result["llm_candidate_count"], 5)
        self.assertEqual(result["llm_candidate_limit"], 5)

    def test_missing_verified_metric_is_reported_without_fabrication(self):
        paper = dict(self.paper)
        paper["journal"] = "Journal Without Verified Metric"
        paper["issns"] = []
        result = self.service.process([paper], {})

        self.assertEqual(result["journal_metric_coverage_count"], 0)
        self.assertEqual(result["journal_metric_missing_count"], 1)
        self.assertEqual(
            result["papers"][0]["evidence_quality"]["journal_impact"]["score"],
            0.0,
        )

    def test_review_accepts_assertions_independently(self):
        paper = self.service.process([self.paper], {})["papers"][0]
        ids = [item["assertion_id"] for item in paper["assertions"]]
        result = LiteratureReviewGate._review_assertions(
            [paper], {"accept": ids[:1], "reject": ids[1:2]}
        )
        self.assertEqual(result["summary"]["accepted_count"], 1)
        self.assertEqual(result["summary"]["rejected_count"], 1)

    def test_b_to_c_contract_requires_accepted_hea_and_element_claims(self):
        paper = self.service.process([self.paper], {})["papers"][0]
        accepted = []
        for assertion in paper["assertions"]:
            if assertion["kind"] in {"element_set", "material_family"}:
                accepted.append({
                    "evidence_id": "E1",
                    "paper_id": paper["paper_id"],
                    **assertion,
                })
        result = nodes.literature_summary_node({
            "route": {"use_rag": True},
            "rag_result": {"synthesis": {}},
            "papers": [paper],
            "literature_review": {"status": "review_completed"},
            "accepted_literature_assertions": accepted,
            "warnings": [],
        })
        contract = result["literature_evidence_contract"]
        self.assertTrue(contract["evidence_backed_candidate_ready"])
        self.assertEqual(
            contract["accepted_explicit_element_sets"][0]["elements"],
            ["Cu", "Fe", "Co", "Ni", "Mn"],
        )

    def test_extraction_node_replaces_b5_selection_with_final_scores(self):
        with patch.object(
            nodes.services.assertion_extraction,
            "process",
            wraps=self.service.process,
        ):
            result = nodes.literature_assertion_extraction_node({
                "merged_literature_result": {"selected": [self.paper]},
                "task_analysis": {
                    "reaction_family": "CO2RR",
                    "target_product": "CO",
                    "material_family": "high_entropy_alloy",
                },
            })
        selected = result["merged_literature_result"]["selected"]
        self.assertEqual(selected[0]["evidence_quality"]["evaluation_phase"], "final")

    def test_four_metal_paper_is_extracted_but_excluded_from_b6(self):
        paper = dict(self.paper)
        paper["title"] = "Cu-Mn-Ni-Zn high-entropy alloy for CO2 reduction"
        paper["abstract"] = (
            "The Cu-Mn-Ni-Zn high-entropy alloy demonstrates CO2RR "
            "activity at 100 mA cm-2."
        )
        with patch.object(
            nodes.services.assertion_extraction,
            "process",
            wraps=self.service.process,
        ):
            result = nodes.literature_assertion_extraction_node({
                "merged_literature_result": {"selected": [paper]},
                "task_analysis": {
                    "reaction_family": "CO2RR",
                    "material_family": "high_entropy_alloy",
                },
            })

        merged = result["merged_literature_result"]
        self.assertEqual(merged["selected_count"], 0)
        self.assertEqual(merged["b6_ineligible_count"], 1)
        self.assertIn(
            "explicit_five_metal_composition_not_found",
            merged["b6_ineligible"][0]["b6_exclusion_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
