import unittest
from unittest.mock import patch

from app.graph.cli import (
    c8_not_executed_reason,
    collect_candidate_review_decision,
    collect_c_stage_execution_decision,
    collect_c7_dft_upgrade_decision,
    collect_dft_input_review_decision,
    collect_review_decision,
)


class GraphCLIC8ReasonTest(unittest.TestCase):
    def test_waiting_bulk_dft_is_not_reported_as_c7_failure(self):
        reason = c8_not_executed_reason({
            "formation_energy_evaluation": {
                "status": "formation_energy_waiting_for_dft",
                "waiting_for_dft_count": 3,
            },
            "dft_formation_energy_queue": [{"structure_id": "S1"}],
            "stability_screening": {},
        })
        self.assertIn("等待 Bulk DFT 形成能", reason)
        self.assertIn("C7 尚未执行", reason)
        self.assertNotIn("没有结构通过 C7", reason)

    def test_completed_c7_with_no_pass_reports_screening_failure(self):
        reason = c8_not_executed_reason({
            "formation_energy_evaluation": {
                "status": "formation_energy_completed",
                "waiting_for_dft_count": 0,
            },
            "dft_formation_energy_queue": [],
            "stability_screening": {
                "status": "stability_screening_completed",
                "passed_count": 0,
            },
        })
        self.assertEqual(
            reason,
            "没有结构通过 C7 稳定性筛选，C8 未执行。",
        )


class GraphCLICStageExecutionTest(unittest.TestCase):
    @patch("builtins.input", side_effect=["2", "recommended prescreen"])
    def test_collects_stability_screening_scope(self, mocked_input):
        result = collect_c_stage_execution_decision({
            "message": "Choose scope.",
            "selected_candidate_ids": ["C1"],
        })

        self.assertEqual(result["mode"], "stability_screening")
        self.assertEqual(result["note"], "recommended prescreen")

    @patch("builtins.input", side_effect=["", ""])
    def test_default_stops_after_candidates(self, mocked_input):
        result = collect_c_stage_execution_decision({
            "selected_candidate_ids": ["C1"],
        })

        self.assertEqual(result["mode"], "candidate_only")


class GraphCLIC7DFTUpgradeTest(unittest.TestCase):
    @patch("builtins.input", side_effect=["s", "d", "continue S1"])
    def test_collects_selected_and_deferred_structures(self, mocked_input):
        result = collect_c7_dft_upgrade_decision({
            "structures": [
                {"structure_id": "S1", "candidate_id": "C1"},
                {"structure_id": "S2", "candidate_id": "C2"},
            ],
        })

        self.assertEqual(result["select"], ["S1"])
        self.assertEqual(result["defer"], ["S2"])

    def test_c8_reason_reports_unapproved_post_c7_gate(self):
        reason = c8_not_executed_reason({
            "stability_screening": {
                "status": "stability_screening_completed",
                "passed_count": 1,
            },
            "c7_dft_upgrade_review": {"selected_count": 0},
            "c_stage_execution_mode": "stability_screening",
        })
        self.assertIn("未批准任何结构", reason)


class GraphCLIReviewTest(
    unittest.TestCase
):
    def setUp(self):
        self.request = {
            "type": (
                "literature_review_required"
            ),
            "message": "请人工审查论文。",
            "candidates": [
                {
                    "evidence_id": "E1",
                    "title": "First paper",
                    "abstract": (
                        "First abstract."
                    ),
                    "doi": "10.1000/one",
                    "journal": (
                        "Example Journal"
                    ),
                    "year": 2025,
                    "retrieval_origin": (
                        "online"
                    ),
                    "quality_level": "A",
                    "quality_score": 14,
                    "quality_issues": [],
                    "version_info": {
                        "has_preprint_version": (
                            False
                        ),
                        "has_formal_version": (
                            True
                        ),
                    },
                },
                {
                    "evidence_id": "E2",
                    "title": "Second paper",
                    "abstract": (
                        "Second abstract."
                    ),
                    "doi": "10.1000/two",
                    "journal": (
                        "Example Journal"
                    ),
                    "year": 2024,
                    "retrieval_origin": (
                        "local"
                    ),
                    "quality_level": "B",
                    "quality_score": 10,
                    "quality_issues": [
                        "摘要证据有限"
                    ],
                    "version_info": {
                        "has_preprint_version": (
                            True
                        ),
                        "has_formal_version": (
                            False
                        ),
                    },
                },
                {
                    "evidence_id": "E3",
                    "title": "Third paper",
                    "abstract": (
                        "Third abstract."
                    ),
                    "doi": "",
                    "journal": "",
                    "year": None,
                    "retrieval_origin": (
                        "online"
                    ),
                    "quality_level": "C",
                    "quality_score": 6,
                    "quality_issues": [
                        "缺少 DOI"
                    ],
                    "version_info": {},
                },
            ],
        }

    @patch(
        "builtins.input",
        side_effect=[
            "a",
            "r",
            "",
            "人工审查测试",
        ],
    )
    def test_collects_accept_reject_and_default_defer(
        self,
        mocked_input,
    ):
        result = collect_review_decision(
            self.request
        )

        self.assertEqual(
            result["accept"],
            ["E1"],
        )

        self.assertEqual(
            result["reject"],
            ["E2"],
        )

        self.assertEqual(
            result["defer"],
            ["E3"],
        )

        self.assertEqual(
            result["note"],
            "人工审查测试",
        )

    @patch(
        "builtins.input",
        side_effect=[
            "invalid",
            "a",
            "d",
            "r",
            "",
        ],
    )
    def test_invalid_action_is_requested_again(
        self,
        mocked_input,
    ):
        result = collect_review_decision(
            self.request
        )

        self.assertEqual(
            result["accept"],
            ["E1"],
        )

        self.assertEqual(
            result["defer"],
            ["E2"],
        )

        self.assertEqual(
            result["reject"],
            ["E3"],
        )


class GraphCLICandidateReviewTest(unittest.TestCase):
    def setUp(self):
        self.request = {
            "type": "candidate_review_required",
            "message": "Review ranked candidates.",
            "total_candidate_count": 100,
            "max_selected": 3,
            "candidates": [
                {
                    "candidate_id": "C1",
                    "rank": 1,
                    "elements": ["Cu", "Fe", "Co", "Ni", "Mn"],
                    "composition": {
                        "Cu": 8,
                        "Fe": 6,
                        "Co": 6,
                        "Ni": 6,
                        "Mn": 6,
                    },
                    "total_score": 80.0,
                    "scores": {},
                },
                {
                    "candidate_id": "C2",
                    "rank": 2,
                    "elements": ["Fe", "Co", "Ni", "Mn", "Mo"],
                    "composition": {
                        "Fe": 7,
                        "Co": 7,
                        "Ni": 6,
                        "Mn": 6,
                        "Mo": 6,
                    },
                    "total_score": 75.0,
                    "scores": {},
                },
                {
                    "candidate_id": "C3",
                    "rank": 3,
                    "elements": ["Cu", "Fe", "Ni", "Cr", "Mn"],
                    "composition": {
                        "Cu": 8,
                        "Fe": 6,
                        "Ni": 6,
                        "Cr": 6,
                        "Mn": 6,
                    },
                    "total_score": 70.0,
                    "scores": {},
                },
            ],
        }

    @patch(
        "builtins.input",
        side_effect=["s", "r", "", "candidate review test"],
    )
    def test_collects_candidate_decisions(self, mocked_input):
        result = collect_candidate_review_decision(self.request)

        self.assertEqual(result["select"], ["C1"])
        self.assertEqual(result["reject"], ["C2"])
        self.assertEqual(result["defer"], ["C3"])
        self.assertEqual(result["note"], "candidate review test")

    @patch(
        "builtins.input",
        side_effect=["invalid", "s", "d", "r", ""],
    )
    def test_invalid_candidate_action_is_retried(
        self,
        mocked_input,
    ):
        result = collect_candidate_review_decision(self.request)

        self.assertEqual(result["select"], ["C1"])
        self.assertEqual(result["defer"], ["C2"])
        self.assertEqual(result["reject"], ["C3"])


class GraphCLIDFTInputReviewTest(unittest.TestCase):
    def setUp(self):
        self.request = {
            "type": "dft_input_review_required",
            "bundles": [{
                "bundle_id": "S1",
                "preview": {
                    "POSCAR": "POSCAR content\n",
                    "INCAR": "INCAR content\n",
                    "KPOINTS": "KPOINTS content\n",
                    "POTCAR": [{
                        "element": "Cu",
                        "potential": "Cu_pv",
                    }],
                    "vasp.slurm": {
                        "job_name": "S1",
                        "partition": "xahcnormal",
                        "full_text": "secret full text",
                    },
                },
            }],
        }

    @patch(
        "builtins.input",
        side_effect=["a", "y", "y", "y", "y", "y", "approved"],
    )
    def test_all_five_confirmations_approve_bundle(self, mocked_input):
        result = collect_dft_input_review_decision(self.request)

        self.assertEqual(result["approve"], ["S1"])
        self.assertEqual(result["defer"], [])
        self.assertTrue(
            all(result["file_confirmations"]["S1"].values())
        )

    @patch(
        "builtins.input",
        side_effect=["a", "y", "y", "n", "y", "y", "needs review"],
    )
    def test_missing_confirmation_defers_bundle(self, mocked_input):
        result = collect_dft_input_review_decision(self.request)

        self.assertEqual(result["approve"], [])
        self.assertEqual(result["defer"], ["S1"])
        self.assertFalse(
            result["file_confirmations"]["S1"]["KPOINTS"]
        )

    @patch(
        "builtins.input",
        side_effect=["m", "把 ENCUT 改成 500", "revise"],
    )
    def test_natural_language_revision_is_returned(self, mocked_input):
        result = collect_dft_input_review_decision(self.request)

        self.assertEqual(result["action"], "revise")
        self.assertEqual(
            result["revision_requests"]["S1"],
            "把 ENCUT 改成 500",
        )
        self.assertEqual(result["approve"], [])

    @patch(
        "builtins.input",
        side_effect=["d", "bulk deferred"],
    )
    def test_bulk_stage_label_reuses_review(self, mocked_input):
        request = dict(self.request)
        request["stage_label"] = "C6D"
        request["type"] = "bulk_dft_input_review_required"

        result = collect_dft_input_review_decision(request)

        self.assertEqual(result["defer"], ["S1"])
        self.assertEqual(result["note"], "bulk deferred")


if __name__ == "__main__":
    unittest.main()
