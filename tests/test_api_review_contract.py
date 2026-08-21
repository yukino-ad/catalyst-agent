from __future__ import annotations

import unittest

from app.api.review_contract import validate_review_decision


class ApiReviewContractTest(unittest.TestCase):
    def test_candidate_decision_is_validated(self):
        review = {
            "items": [{"candidate_id": "C1"}, {"candidate_id": "C2"}],
            "max_selected": 1,
        }
        result = validate_review_decision(
            review,
            "candidate_review_required",
            {"select": ["C1"], "reject": ["C2"]},
        )
        self.assertEqual(result["select"], ["C1"])
        self.assertEqual(result["reject"], ["C2"])

    def test_unknown_identifier_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown review identifiers"):
            validate_review_decision(
                {"items": [{"candidate_id": "C1"}], "max_selected": 1},
                "candidate_review_required",
                {"select": ["C99"]},
            )

    def test_missing_decision_is_rejected_instead_of_deferred(self):
        with self.assertRaisesRegex(ValueError, "explicit decision"):
            validate_review_decision(
                {"items": [{"bundle_id": "B1"}]},
                "dft_input_review_required",
                {"approve": [], "reject": [], "defer": []},
            )

    def test_selection_limit_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "At most 1"):
            validate_review_decision(
                {
                    "items": [{"candidate_id": "C1"}, {"candidate_id": "C2"}],
                    "max_selected": 1,
                },
                "candidate_review_required",
                {"select": ["C1", "C2"]},
            )

    def test_execution_mode_must_be_advertised(self):
        review = {"options": [{"mode": "stability_screening"}]}
        result = validate_review_decision(
            review,
            "c_stage_execution_review_required",
            {"mode": "stability_screening"},
        )
        self.assertEqual(result["mode"], "stability_screening")
        with self.assertRaisesRegex(ValueError, "Unknown execution"):
            validate_review_decision(
                review,
                "c_stage_execution_review_required",
                {"mode": "remote_submit"},
            )

    def test_dft_execution_mode_must_be_advertised(self):
        result = validate_review_decision(
            {"options": [{"mode": "relax_only"}]},
            "dft_execution_options_required",
            {"mode": "relax_only"},
        )
        self.assertEqual(result["mode"], "relax_only")

    def test_remote_submission_requires_exact_confirmation_phrase(self):
        review = {
            "items": [{"job_id": "J1"}],
            "plan_digest": "digest-1",
            "confirmation_phrase": "SUBMIT task-1",
        }
        with self.assertRaisesRegex(ValueError, "Confirmation phrase"):
            validate_review_decision(
                review,
                "remote_submission_review_required",
                {
                    "action": "approve_submission",
                    "approved_job_ids": ["J1"],
                    "confirmation_text": "SUBMIT wrong-task",
                },
            )
        result = validate_review_decision(
            review,
            "remote_submission_review_required",
            {
                "action": "approve_submission",
                "approved_job_ids": ["J1"],
                "confirmation_text": "SUBMIT task-1",
            },
        )
        self.assertEqual(result["approved_job_ids"], ["J1"])

    def test_slab_review_approve_is_valid(self):
        result = validate_review_decision(
            {"items": [{"slab_id": "S1"}], "max_approved": 1},
            "slab_review_required",
            {"approve": ["S1"]},
        )
        self.assertEqual(result["approve"], ["S1"])

    def test_bulk_dft_review_requires_all_files(self):
        review = {
            "items": [{"bundle_id": "B1"}],
            "required_files": ["POSCAR", "INCAR", "KPOINTS", "POTCAR", "vasp.slurm"],
        }
        confirmations = {name: True for name in review["required_files"]}
        result = validate_review_decision(
            review,
            "bulk_dft_input_review_required",
            {"approve": ["B1"], "file_confirmations": {"B1": confirmations}},
        )
        self.assertEqual(result["approve"], ["B1"])

    def test_bulk_dft_review_rejects_missing_file_confirmation(self):
        with self.assertRaisesRegex(ValueError, "All five files"):
            validate_review_decision(
                {
                    "items": [{"bundle_id": "B1"}],
                    "required_files": ["POSCAR", "INCAR", "KPOINTS", "POTCAR", "vasp.slurm"],
                },
                "dft_input_review_required",
                {
                    "approve": ["B1"],
                    "file_confirmations": {"B1": {"POSCAR": True}},
                },
            )

    def test_dft_revision_can_replace_item_classification(self):
        result = validate_review_decision(
            {
                "items": [{"bundle_id": "B1"}, {"bundle_id": "B2"}],
                "required_files": ["POSCAR", "INCAR"],
            },
            "dft_input_review_required",
            {
                "action": "revise",
                "approve": ["B2"],
                "revision_requests": {"B1": "将 ENCUT 修改为 500 eV"},
                "file_confirmations": {
                    "B2": {"POSCAR": True, "INCAR": True},
                },
            },
        )
        self.assertEqual(result["action"], "revise")
        self.assertEqual(result["revision_requests"]["B1"], "将 ENCUT 修改为 500 eV")

    def test_dft_revision_and_approval_cannot_target_same_bundle(self):
        with self.assertRaisesRegex(ValueError, "both revised and classified"):
            validate_review_decision(
                {"items": [{"bundle_id": "B1"}], "required_files": []},
                "dft_input_review_required",
                {
                    "approve": ["B1"],
                    "revision_requests": {"B1": "修改 KPOINTS 为 3 3 1"},
                },
            )

    def test_adsorption_energy_review_approve_is_valid(self):
        result = validate_review_decision(
            {"items": [{"adsorption_energy_id": "AE1"}]},
            "adsorption_energy_review_required",
            {"approve": ["AE1"]},
        )
        self.assertEqual(result["approve"], ["AE1"])

    def test_literature_assertions_from_rejected_papers_are_ignored(self):
        result = validate_review_decision(
            {
                "items": [
                    {"evidence_id": "E1", "assertions": [{"assertion_id": "E1::A1"}]},
                    {"evidence_id": "E2", "assertions": [{"assertion_id": "E2::A1"}]},
                ],
            },
            "literature_review_required",
            {
                "accept": ["E1"],
                "reject": ["E2"],
                "assertions": {"accept": ["E1::A1"], "defer": ["E2::A1"]},
            },
        )
        self.assertEqual(result["assertions"]["accept"], ["E1::A1"])
        self.assertEqual(result["assertions"]["defer"], [])


if __name__ == "__main__":
    unittest.main()
