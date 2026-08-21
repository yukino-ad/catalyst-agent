import tempfile
import unittest
from pathlib import Path

from tools.literature.local_retriever import (
    LocalLiteratureRetriever,
)
from tools.literature.repository import (
    LiteratureRepository,
)
from tools.literature.schemas import PaperRecord


class LocalLiteratureRetrieverTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )

        database_path = (
            Path(self.temporary_directory.name)
            / "literature_test.db"
        )

        self.repository = LiteratureRepository(
            database_path
        )

        self.repository.upsert(
            PaperRecord(
                paper_id="openalex:direct",
                title=(
                    "High entropy alloys for "
                    "CO2 reduction to CO"
                ),
                abstract=(
                    "This study investigates "
                    "CO2 reduction and selective "
                    "CO production."
                ),
                year=2025,
                journal="Example Journal",
                doi="10.1000/direct",
                source="test",
            )
        )

        self.repository.upsert(
            PaperRecord(
                paper_id="openalex:indirect",
                title=(
                    "High entropy alloys for "
                    "oxygen evolution"
                ),
                abstract=(
                    "This work investigates "
                    "the oxygen evolution reaction."
                ),
                year=2024,
                journal="Example Journal",
                doi="10.1000/indirect",
                source="test",
            )
        )

        self.repository.upsert(
            PaperRecord(
                paper_id="openalex:no-abstract",
                title=(
                    "CO2 reduction to CO using "
                    "high entropy catalysts"
                ),
                abstract="",
                year=2023,
                journal="Example Journal",
                doi="10.1000/no-abstract",
                source="test",
            )
        )

        self.retriever = LocalLiteratureRetriever(
            repository=self.repository,
        )

        self.task_analysis = {
            "reaction_family": "CO2RR",
            "target_product": "CO",
        }

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_direct_paper_is_ranked_first(self):
        result = self.retriever.retrieve(
            query=(
                "high entropy alloy "
                "CO2 reduction to CO"
            ),
            keywords=["CO2RR", "CO selectivity"],
            task_analysis=self.task_analysis,
            recall_count=10,
            final_count=3,
        )

        self.assertGreater(
            result["selected_count"],
            0,
        )

        self.assertEqual(
            result["selected"][0]["paper_id"],
            "openalex:direct",
        )

    def test_selected_papers_have_quality(self):
        result = self.retriever.retrieve(
            query="high entropy CO2 reduction",
            task_analysis=self.task_analysis,
            recall_count=10,
            final_count=3,
        )

        for paper in result["selected"]:
            self.assertIn(
                "evidence_quality",
                paper,
            )
            self.assertIn(
                "retrieval_scores",
                paper,
            )

    def test_final_count_limits_output(self):
        result = self.retriever.retrieve(
            query="high entropy alloy",
            task_analysis=self.task_analysis,
            recall_count=10,
            final_count=2,
        )

        self.assertLessEqual(
            result["selected_count"],
            2,
        )

    def test_missing_abstract_cannot_be_a_level(self):
        result = self.retriever.retrieve(
            query="CO2 reduction to CO",
            task_analysis=self.task_analysis,
            recall_count=10,
            final_count=3,
        )

        paper = next(
            item
            for item in result["selected"]
            if item["paper_id"]
            == "openalex:no-abstract"
        )

        self.assertNotEqual(
            paper["evidence_quality"][
                "quality_level"
            ],
            "A",
        )

    def test_invalid_counts_raise_error(self):
        with self.assertRaises(ValueError):
            self.retriever.retrieve(
                query="CO2 reduction",
                recall_count=2,
                final_count=3,
            )

    def test_test_database_is_isolated(self):
        self.assertEqual(
            self.repository.count(),
            3,
        )


if __name__ == "__main__":
    unittest.main()