import tempfile
import unittest
from pathlib import Path

from tools.literature.repository import (
    LiteratureRepository,
)
from tools.literature.review_gate import (
    LiteratureReviewGate,
)
from tools.literature.schemas import PaperRecord


def make_paper(
    evidence_id: str,
    paper_id: str,
    title: str,
    doi: str,
    origin: str = "online",
    source: str = "OpenAlex",
) -> dict:
    return {
        "evidence_id": evidence_id,
        "paper_id": paper_id,
        "title": title,
        "abstract": (
            "This study investigates CO2 "
            "reduction and selective CO production."
        ),
        "year": 2025,
        "journal": "Example Journal",
        "doi": doi,
        "url": "",
        "source": source,
        "summary": "",
        "assertions": [],
        "retrieval_origin": origin,
        "review_status": "pending_review",
        "stored_in_repository": (
            origin != "online"
        ),
    }


class LiteratureReviewGateTest(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )

        database_path = (
            Path(self.temporary_directory.name)
            / "review_test.db"
        )

        self.repository = LiteratureRepository(
            database_path
        )

        self.gate = LiteratureReviewGate(
            repository=self.repository
        )

        self.candidates = [
            make_paper(
                "E1",
                "openalex:W1",
                "First online paper",
                "10.1000/one",
                origin="online",
            ),
            make_paper(
                "E2",
                "openalex:W2",
                "Second online paper",
                "10.1000/two",
                origin="online",
            ),
            make_paper(
                "E3",
                "openalex:W3",
                "Existing local paper",
                "10.1000/three",
                origin="local",
            ),
        ]

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_review_classifies_all_decisions(self):
        result = self.gate.review(
            candidates=self.candidates,
            decision={
                "accept": ["E1"],
                "reject": ["E2"],
                "defer": ["E3"],
                "note": "人工检查完成",
            },
        )

        self.assertEqual(
            result["status"],
            "review_completed",
        )
        self.assertEqual(
            result["accepted_count"],
            1,
        )
        self.assertEqual(
            result["rejected_count"],
            1,
        )
        self.assertEqual(
            result["deferred_count"],
            1,
        )
        self.assertEqual(
            result["accepted"][0][
                "review_status"
            ],
            "accepted",
        )

    def test_unclassified_papers_are_deferred(self):
        result = self.gate.review(
            candidates=self.candidates,
            decision={
                "accept": ["E1"],
            },
        )

        self.assertEqual(
            result["decision"]["defer"],
            ["E2", "E3"],
        )
        self.assertEqual(
            result[
                "unclassified_moved_to_defer"
            ],
            ["E2", "E3"],
        )

    def test_assertions_from_rejected_papers_are_ignored(self):
        candidates = [dict(item) for item in self.candidates[:2]]
        candidates[0]["assertions"] = [{"assertion_id": "E1::A1", "kind": "reaction"}]
        candidates[1]["assertions"] = [{"assertion_id": "E2::A1", "kind": "reaction"}]
        result = self.gate.review(
            candidates=candidates,
            decision={
                "accept": ["E1"],
                "reject": ["E2"],
                "assertions": {"accept": ["E1::A1"], "defer": ["E2::A1"]},
            },
        )
        self.assertEqual(result["accepted_assertions"][0]["assertion_id"], "E1::A1")
        self.assertEqual(result["assertion_review"]["candidate_count"], 1)

    def test_conflicting_decision_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "重复分类",
        ):
            self.gate.review(
                candidates=self.candidates,
                decision={
                    "accept": ["E1"],
                    "reject": ["E1"],
                },
            )

    def test_unknown_evidence_id_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "不存在的证据编号",
        ):
            self.gate.review(
                candidates=self.candidates,
                decision={
                    "accept": ["E99"],
                },
            )

    def test_string_decision_is_supported(self):
        result = self.gate.review(
            candidates=self.candidates,
            decision={
                "accept": "e1",
                "reject": "e2",
                "defer": "e3",
            },
        )

        self.assertEqual(
            result["decision"]["accept"],
            ["E1"],
        )
        self.assertEqual(
            result["decision"]["reject"],
            ["E2"],
        )
        self.assertEqual(
            result["decision"]["defer"],
            ["E3"],
        )

    def test_human_acceptance_allows_ideal_modeling_hypothesis(self):
        candidate = {
            **self.candidates[0],
            "c_stage_evidence_eligible": False,
        }
        result = self.gate.review(
            candidates=[candidate],
            decision={"accept": ["E1"]},
        )
        accepted = result["accepted"][0]
        self.assertEqual(
            accepted["evidence_use_mode"],
            "ideal_modeling_hypothesis",
        )
        self.assertNotIn("verification_level", accepted)
        self.assertFalse(accepted["requires_secondary_verification"])

    def test_only_accepted_online_paper_is_stored(self):
        review_result = self.gate.review(
            candidates=self.candidates,
            decision={
                "accept": ["E1", "E3"],
                "reject": ["E2"],
            },
        )

        commit_result = (
            self.gate.commit_accepted(
                review_result
            )
        )

        self.assertEqual(
            commit_result["stored_count"],
            1,
        )
        self.assertEqual(
            commit_result["skipped_count"],
            1,
        )
        self.assertEqual(
            self.repository.count(),
            1,
        )
        self.assertEqual(
            commit_result["stored"][0][
                "paper_id"
            ],
            "openalex:W1",
        )

    def test_duplicate_doi_is_not_stored(self):
        self.repository.upsert(
            PaperRecord(
                paper_id="openalex:EXISTING",
                title="Existing database paper",
                abstract="Existing abstract.",
                year=2024,
                journal="Example Journal",
                doi="https://doi.org/10.1000/one",
                source="OpenAlex",
            )
        )

        review_result = self.gate.review(
            candidates=[self.candidates[0]],
            decision={
                "accept": ["E1"],
            },
        )

        commit_result = (
            self.gate.commit_accepted(
                review_result
            )
        )

        self.assertEqual(
            commit_result["stored_count"],
            0,
        )
        self.assertEqual(
            commit_result["skipped_count"],
            1,
        )
        self.assertIn(
            "相同 DOI",
            commit_result["skipped"][0][
                "reason"
            ],
        )
        self.assertEqual(
            self.repository.count(),
            1,
        )

    def test_sample_record_is_not_stored(self):
        sample = make_paper(
            "E1",
            "sample:1",
            "Development sample",
            "",
            origin="online",
            source="sample",
        )

        review_result = self.gate.review(
            candidates=[sample],
            decision={
                "accept": ["E1"],
            },
        )

        commit_result = (
            self.gate.commit_accepted(
                review_result
            )
        )

        self.assertEqual(
            commit_result["stored_count"],
            0,
        )
        self.assertEqual(
            commit_result["skipped_count"],
            1,
        )
        self.assertEqual(
            self.repository.count(),
            0,
        )

    def test_rejected_and_deferred_are_not_stored(self):
        review_result = self.gate.review(
            candidates=self.candidates,
            decision={
                "reject": ["E1"],
                "defer": ["E2", "E3"],
            },
        )

        commit_result = (
            self.gate.commit_accepted(
                review_result
            )
        )

        self.assertEqual(
            review_result["accepted_count"],
            0,
        )
        self.assertEqual(
            commit_result["stored_count"],
            0,
        )
        self.assertEqual(
            self.repository.count(),
            0,
        )


if __name__ == "__main__":
    unittest.main()
