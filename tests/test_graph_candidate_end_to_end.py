import os
import unittest
from unittest.mock import patch

from langgraph.types import Command

from app.graph import nodes


def accepted_candidate_paper() -> dict:
    return {
        "evidence_id": "E1",
        "paper_id": "openalex:C4_TEST",
        "title": "High entropy alloys for CO2 reduction",
        "abstract": (
            "A Cu Fe Co Ni Mn high entropy alloy is studied "
            "for electrochemical CO2 reduction."
        ),
        "year": 2025,
        "journal": "Test Journal",
        "doi": "10.1000/c4-test",
        "url": "",
        "source": "OpenAlex",
        "summary": "",
        "assertions": [{
            "kind": "element_set",
            "value": ["Cu", "Fe", "Co", "Ni", "Mn"],
            "evidence_level": "explicit",
            "inferred": False,
        }],
        "elements": ["Cu", "Fe", "Co", "Ni", "Mn"],
        "retrieval_origin": "online",
        "review_status": "pending_review",
        "stored_in_repository": False,
        "evidence_quality": {
            "quality_level": "A",
            "quality_score": 14,
            "issues": [],
        },
        "version_info": {
            "has_preprint_version": False,
            "has_formal_version": True,
        },
    }


def ranked_candidates() -> list[dict]:
    return [
        {
            "schema_version": "c2.0",
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
            "atomic_fractions": {
                "Cu": 0.25,
                "Fe": 0.1875,
                "Co": 0.1875,
                "Ni": 0.1875,
                "Mn": 0.1875,
            },
            "scores": {
                "literature_support": 100.0,
                "constraint_preference": 100.0,
                "element_abundance": 66.25,
                "price": 76.875,
                "toxicity_environment": 58.4375,
                "synthesis_difficulty": 94.125,
            },
            "total_score": 80.0,
            "details": {
                "literature_support": {
                    "best_evidence": {
                        "evidence_id": "E1",
                        "title": (
                            "High entropy alloys for "
                            "CO2 reduction"
                        ),
                        "doi": "10.1000/c4-test",
                    },
                },
                "toxicity_environment": {
                    "highest_risk_elements": ["Co", "Ni"],
                },
                "synthesis_difficulty": {
                    "active_process_risks": {},
                },
            },
            "ranking_only": True,
            "eliminated": False,
            "decision": "scored_not_filtered",
        },
        {
            "schema_version": "c2.0",
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
            "scores": {
                "literature_support": 40.0,
                "constraint_preference": 50.0,
                "element_abundance": 55.0,
                "price": 60.0,
                "toxicity_environment": 58.0,
                "synthesis_difficulty": 70.0,
            },
            "total_score": 60.0,
            "details": {
                "literature_support": {
                    "best_evidence": {
                        "evidence_id": "E1",
                        "title": (
                            "High entropy alloys for "
                            "CO2 reduction"
                        ),
                        "doi": "10.1000/c4-test",
                    },
                },
                "toxicity_environment": {
                    "highest_risk_elements": ["Co", "Ni"],
                },
                "synthesis_difficulty": {
                    "active_process_risks": {"Mo": 10.0},
                },
            },
            "ranking_only": True,
            "eliminated": False,
            "decision": "scored_not_filtered",
        },
    ]


def generation_result() -> dict:
    candidates = ranked_candidates()

    return {
        "schema_version": "c3.0",
        "generation_stage": "c3",
        "candidate_count": len(candidates),
        "legal_combination_count": len(candidates),
        "rejected_counts": {
            "missing_required_element": 0,
            "too_many_p_block_elements": 0,
        },
        "variants_per_combination": 1,
        "max_candidates": None,
        "truncated": False,
        "scoring_applied": True,
        "scoring_stage": "c2",
        "candidates": candidates,
        "warnings": [],
    }


def structure_modeling_result() -> dict:
    return {
        "schema_version": "c5.0",
        "stage": "c5",
        "status": "structure_modeling_completed",
        "selected_candidate_count": 1,
        "modeled_candidate_count": 1,
        "structure_count": 1,
        "structures": [{
            "schema_version": "c5.0",
            "structure_id": "C1-fcc-01",
            "candidate_id": "C1",
            "atom_count": 32,
            "cif_path": "test.cif",
            "poscar_path": "POSCAR.vasp",
            "formation_energy": None,
            "eligible_for_slab": False,
        }],
        "failure_count": 0,
        "failures": [],
        "next_stage": "c6_formation_energy",
        "formation_energy_evaluated": False,
        "stability_evaluated": False,
        "slab_generated": False,
    }


def formation_energy_result() -> dict:
    return {
        "schema_version": "c6.0",
        "stage": "c6",
        "status": "formation_energy_completed",
        "structure_count": 1,
        "cgcnn_predicted_count": 1,
        "waiting_for_dft_count": 0,
        "failed_count": 0,
        "structures": [{
            "structure_id": "C1-fcc-01",
            "candidate_id": "C1",
            "atom_count": 32,
            "formation_energy_route": "cgcnn",
            "formation_energy_status": "predicted",
            "formation_energy": 0.03,
            "formation_energy_unit": "eV/atom",
            "eligible_for_slab": False,
        }],
        "dft_queue": [],
        "error_count": 0,
        "errors": [],
        "formation_energy_threshold_applied": False,
        "stability_evaluated": False,
        "slab_generated": False,
        "next_stage": "c7_stability_screening",
    }


def stability_screening_result() -> dict:
    passed_structure = {
        "structure_id": "C1-fcc-01",
        "candidate_id": "C1",
        "formation_energy": 0.03,
        "formation_energy_pass": True,
        "delta_percent": 4.0,
        "delta_pass": True,
        "omega": 2.0,
        "omega_pass": True,
        "stability_decision": "passed",
        "eligible_for_slab": True,
    }

    return {
        "schema_version": "c7.0",
        "stage": "c7",
        "status": (
            "stability_screening_completed_all_passed"
        ),
        "structure_count": 1,
        "passed_count": 1,
        "failed_count": 0,
        "pending_count": 0,
        "evaluation_error_count": 0,
        "structures": [passed_structure],
        "slab_eligible_structures": [passed_structure],
        "errors": [],
        "criteria": {
            "formation_energy": "< 0.05 eV/atom",
            "atomic_size_delta": "<= 6.6%",
            "omega": ">= 1.1",
            "all_required": True,
        },
        "slab_generated": False,
        "next_stage": "c8_slab_generation",
    }


def slab_generation_result() -> dict:
    return {
        "schema_version": "c8.0",
        "stage": "c8",
        "status": "slab_generation_completed",
        "input_structure_count": 1,
        "slab_count": 1,
        "failure_count": 0,
        "slabs": [{
            "slab_id": "C1-fcc-01-slab111",
            "source_structure_id": "C1-fcc-01",
            "atom_count": 48,
            "vacuum_angstrom": 18.0,
            "cif_path": "slab.cif",
            "poscar_path": "slab.vasp",
        }],
        "failures": [],
        "miller_index": [1, 1, 1],
        "expected_atom_count": 48,
        "vacuum_angstrom": 18.0,
        "stability_recalculated": False,
        "next_stage": "structure_visualization",
    }


def slab_quality_result() -> dict:
    passed_slab = {
        **slab_generation_result()["slabs"][0],
        "schema_version": "c9.0",
        "stage": "c9_quality",
        "element_count": 5,
        "minimum_distance_angstrom": 2.45,
        "measured_vacuum_angstrom": 18.0,
        "fixed_atom_count": 32,
        "movable_atom_count": 16,
        "failed_checks": [],
        "quality_decision": "passed",
        "eligible_for_dft_review": True,
    }

    return {
        "schema_version": "c9.0",
        "stage": "c9_quality",
        "status": "slab_quality_completed_all_passed",
        "input_slab_count": 1,
        "checked_count": 1,
        "passed_count": 1,
        "failed_count": 0,
        "error_count": 0,
        "reports": [passed_slab],
        "quality_passed_slabs": [passed_slab],
        "errors": [],
        "next_stage": "c9_slab_review",
    }


def dft_input_preview_result() -> dict:
    return {
        "schema_version": "c10.0",
        "stage": "c10_preview",
        "status": "dft_input_preview_completed",
        "task_id": "c4-double-interrupt",
        "bundle_count": 1,
        "bundles": [{
            "schema_version": "c10.0",
            "bundle_id": "C1-fcc-01-slab111",
            "task_id": "c4-double-interrupt",
            "slab_id": "C1-fcc-01-slab111",
            "candidate_id": "C1",
            "elements": ["Cu", "Co", "Fe", "Mn", "Al"],
            "counts": [10, 10, 10, 10, 8],
            "atom_count": 48,
            "preview": {
                "POSCAR": "test POSCAR\n",
                "INCAR": "test INCAR\n",
                "KPOINTS": "test KPOINTS\n",
                "POTCAR": [{
                    "element": "Cu",
                    "potential": "Cu_pv",
                    "exists": True,
                }],
                "vasp.slurm": {
                    "job_name": "C1-fcc-01-slab111",
                    "partition": "xahcnormal",
                    "full_text": "test slurm\n",
                },
            },
            "preview_digest": "test-digest",
            "formal_files_written": False,
        }],
        "formal_files_written": False,
        "requires_human_confirmation": True,
    }


def dft_input_preparation_result() -> dict:
    return {
        "schema_version": "c10.0",
        "stage": "c10_finalize",
        "status": "dft_input_preparation_completed",
        "approved_bundle_count": 1,
        "prepared_job_count": 1,
        "failure_count": 0,
        "jobs": [{
            "job_id": "C1-fcc-01-slab111",
            "slab_id": "C1-fcc-01-slab111",
            "candidate_id": "C1",
            "job_dir": "data/dft_inputs/test/C1-fcc-01-slab111",
            "file_count": 5,
            "element_order": ["Cu", "Co", "Fe", "Mn", "Al"],
            "potcar_order": [
                "Cu_pv", "Co_pv", "Fe_pv", "Mn_pv", "Al",
            ],
            "submission_ready": True,
            "submitted": False,
        }],
        "failures": [],
        "submission_performed": False,
    }


def dft_local_preflight_result() -> dict:
    job = {
        **dft_input_preparation_result()["jobs"][0],
        "job_source": "c10_slab",
        "local_preflight_status": "passed",
        "local_preflight_passed": True,
        "checks": [],
        "errors": [],
        "submission_performed": False,
    }

    return {
        "schema_version": "c11.2",
        "stage": "dft_local_preflight",
        "status": "dft_local_preflight_passed",
        "job_source": "c10_slab",
        "job_count": 1,
        "passed_count": 1,
        "failed_count": 0,
        "jobs": [job],
        "eligible_jobs": [job],
        "submission_performed": False,
        "next_stage": "c11.3_cluster_readonly_preflight",
    }


def cluster_readonly_preflight_result() -> dict:
    jobs = dft_local_preflight_result()[
        "eligible_jobs"
    ]

    return {
        "schema_version": "c11.3",
        "stage": "cluster_readonly_preflight",
        "status": (
            "cluster_readonly_preflight_passed"
        ),
        "cluster": {
            "host": "cluster.example.edu",
            "port": 22,
            "user": "tes***er",
            "remote_hostname": "login-test",
            "remote_root": (
                "/work/test_user/catalyst-agent"
            ),
            "slurm_partition": "normal",
            "vasp_module": "vasp-test",
            "vasp_executable": "vasp_std",
            "vasp_command": "srun vasp_std",
        },
        "job_count": 1,
        "passed_count": 1,
        "failed_count": 0,
        "jobs": jobs,
        "eligible_jobs": jobs,
        "checks": [],
        "errors": [],
        "upload_performed": False,
        "remote_write_performed": False,
        "submission_performed": False,
        "next_stage": (
            "c11.4_remote_submission_review"
        ),
    }


def remote_execution_plan_result() -> dict:
    job = {
        **dft_local_preflight_result()[
            "eligible_jobs"
        ][0],
        "remote_job_directory": (
            "/work/test/runs/c4-double-interrupt/"
            "C1-fcc-01-slab111"
        ),
        "files": [],
    }

    return {
        "schema_version": "c11.4.1",
        "stage": "remote_execution_plan",
        "status": "remote_execution_plan_ready",
        "task_id": "c4-double-interrupt",
        "job_source": "c10_slab",
        "remote_batch_directory": (
            "/work/test/runs/c4-double-interrupt"
        ),
        "plan_digest": "test-plan-digest",
        "job_count": 1,
        "jobs": [job],
        "required_human_confirmation": True,
        "overwrite_allowed": False,
        "remote_write_performed": False,
        "upload_performed": False,
        "submission_performed": False,
    }


def remote_upload_result() -> dict:
    job = {
        **remote_execution_plan_result()["jobs"][0],
        "upload_status": "uploaded_and_verified",
        "remote_write_performed": True,
        "upload_performed": True,
        "remote_hash_verified": True,
        "submission_performed": False,
        "errors": [],
    }

    return {
        "schema_version": "c11.4.2",
        "stage": "remote_upload",
        "status": "remote_upload_verified",
        "approved_count": 1,
        "uploaded_count": 1,
        "verified_count": 1,
        "failed_count": 0,
        "jobs": [job],
        "verified_jobs": [job],
        "errors": [],
        "remote_write_performed": True,
        "upload_performed": True,
        "submission_performed": False,
    }


def remote_submission_result() -> dict:
    job = {
        **remote_upload_result()["verified_jobs"][0],
        "submission_approved": True,
        "submission_performed": True,
        "submission_status": "submitted",
        "slurm_job_id": "123456",
        "submitted_at": "2026-07-23T00:00:00+00:00",
        "errors": [],
    }

    return {
        "schema_version": "c11.4.3",
        "stage": "remote_submission",
        "status": "remote_submission_completed",
        "approved_count": 1,
        "submitted_count": 1,
        "unknown_count": 0,
        "failed_count": 0,
        "jobs": [job],
        "submitted_jobs": [job],
        "slurm_job_ids": ["123456"],
        "errors": [],
        "submission_performed": True,
        "automatic_retry_allowed": False,
        "next_stage": "c11.5_job_monitoring",
    }


def submission_recording_result() -> dict:
    return {
        "schema_version": "c11.5.1",
        "stage": "submission_recording",
        "status": "submission_jobs_recorded",
        "recorded_count": 1,
        "new_record_count": 1,
        "existing_count": 0,
        "failed_count": 0,
        "records": [{
            "slurm_job_id": "123456",
            "task_id": "c4-double-interrupt",
            "job_id": "C1-fcc-01-slab111",
            "job_source": "c10_slab",
            "remote_job_directory": (
                "/work/test/runs/c4-double-interrupt/"
                "C1-fcc-01-slab111"
            ),
            "plan_digest": "test-plan-digest",
            "monitoring_status": "awaiting_first_poll",
            "scheduler_state": "UNKNOWN",
            "terminal": False,
        }],
        "errors": [],
        "latest_manifest_path": (
            "data/cluster_jobs/latest_submission.json"
        ),
        "next_stage": "c11.5.2_job_monitoring",
    }


class GraphCandidateEndToEndTest(unittest.TestCase):
    @patch.object(
        nodes.services.submitted_job_repository,
        "record_submission",
        return_value=submission_recording_result(),
    )
    def test_seven_interrupts_finish_with_submission(
        self,
        mocked_record_submission,
    ):
        paper = accepted_candidate_paper()

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
            "candidates": [paper],
            "warnings": [],
        }
        merged_result = {
            "status": "completed",
            "selected": [paper],
            "rejected": [],
            "local_input_count": 0,
            "online_input_count": 1,
            "unique_count": 1,
            "duplicate_count": 0,
            "selected_count": 1,
            "warnings": [],
        }
        commit_result = {
            "status": "commit_completed",
            "database_count_before": 0,
            "database_count_after": 1,
            "stored_count": 1,
            "skipped_count": 0,
            "error_count": 0,
            "stored": [{
                "evidence_id": "E1",
                "paper_id": "openalex:C4_TEST",
                "title": paper["title"],
            }],
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
                nodes.services.evidence_merger,
                "merge",
                return_value=merged_result,
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
                    "answer": "Accepted evidence summary [E1]",
                    "citations": ["E1"],
                    "mode": "test",
                },
            ),
            patch.object(
                nodes.services.candidate_generator,
                "generate_and_score",
                return_value=generation_result(),
            ),
            patch.object(
                nodes.services.structure_modeler,
                "model_candidates",
                return_value=structure_modeling_result(),
            ),
            patch.object(
                nodes.services.formation_energy_evaluator,
                "evaluate",
                return_value=formation_energy_result(),
            ),
            patch.object(
                nodes.services.stability_screening_evaluator,
                "evaluate",
                return_value=stability_screening_result(),
            ),
            patch.object(
                nodes.services.slab_generation_service,
                "generate",
                return_value=slab_generation_result(),
            ),
            patch.object(
                nodes.services.slab_quality_inspector,
                "inspect",
                return_value=slab_quality_result(),
            ),
            patch.object(
                nodes.services.vasp_input_bundle_service,
                "preview",
                return_value=dft_input_preview_result(),
            ),
            patch.object(
                nodes.services.vasp_input_bundle_service,
                "finalize",
                return_value=dft_input_preparation_result(),
            ),
            patch.object(
                nodes.services.dft_local_preflight_service,
                "inspect",
                return_value=dft_local_preflight_result(),
            ),
            patch.object(
                nodes.services
                .cluster_readonly_preflight_service,
                "inspect",
                return_value=(
                    cluster_readonly_preflight_result()
                ),
            ),
            patch.object(
                nodes.services.remote_execution_plan_service,
                "plan",
                return_value=remote_execution_plan_result(),
            ),
            patch.object(
                nodes.services.remote_upload_service,
                "upload",
                return_value=remote_upload_result(),
            ),
            patch.object(
                nodes.services.remote_submission_service,
                "submit",
                return_value=remote_submission_result(),
            ),
        ):
            from app.graph.workflow import build_graph

            graph = build_graph()
            config = {
                "configurable": {
                    "thread_id": "c4-double-interrupt",
                }
            }

            first = graph.invoke(
                {
                    "task_id": "c4-double-interrupt",
                    "question": (
                        "设计用于 CO2 还原生成 CO "
                        "的高熵合金催化剂"
                    ),
                    "errors": [],
                    "warnings": [],
                    "retry_count": 0,
                    "status": "created",
                },
                config=config,
            )

            self.assertIn("__interrupt__", first)

            first_interrupt = first[
                "__interrupt__"
            ][0].value

            self.assertEqual(
                first_interrupt["type"],
                "literature_review_required",
            )

            second = graph.invoke(
                Command(
                    resume={
                        "accept": ["E1"],
                        "reject": [],
                        "defer": [],
                        "note": "Accept E1 for testing.",
                    }
                ),
                config=config,
            )

            self.assertIn("__interrupt__", second)

            second_interrupt = second[
                "__interrupt__"
            ][0].value

            self.assertEqual(
                second_interrupt["type"],
                "candidate_review_required",
            )
            self.assertEqual(
                second_interrupt["total_candidate_count"],
                2,
            )
            self.assertEqual(
                second_interrupt["candidates"][0][
                    "candidate_id"
                ],
                "C1",
            )

            third = graph.invoke(
                Command(
                    resume={
                        "select": ["C1"],
                        "reject": ["C2"],
                        "defer": [],
                        "note": "Select C1 for later modeling.",
                    }
                ),
                config=config,
            )

            self.assertIn("__interrupt__", third)

            third_interrupt = third[
                "__interrupt__"
            ][0].value

            self.assertEqual(
                third_interrupt["type"],
                "slab_review_required",
            )
            self.assertEqual(
                third_interrupt["slabs"][0]["slab_id"],
                "C1-fcc-01-slab111",
            )

            fourth = graph.invoke(
                Command(
                    resume={
                        "approve": [
                            "C1-fcc-01-slab111"
                        ],
                        "reject": [],
                        "defer": [],
                        "note": "Approve C9 slab for DFT.",
                    }
                ),
                config=config,
            )

            self.assertIn("__interrupt__", fourth)

            fourth_interrupt = fourth[
                "__interrupt__"
            ][0].value

            self.assertEqual(
                fourth_interrupt["type"],
                "dft_input_review_required",
            )
            self.assertEqual(
                fourth_interrupt["bundles"][0]["bundle_id"],
                "C1-fcc-01-slab111",
            )

            fifth = graph.invoke(
                Command(
                    resume={
                        "approve": ["C1-fcc-01-slab111"],
                        "reject": [],
                        "defer": [],
                        "file_confirmations": {
                            "C1-fcc-01-slab111": {
                                "POSCAR": True,
                                "INCAR": True,
                                "KPOINTS": True,
                                "POTCAR": True,
                                "vasp.slurm": True,
                            }
                        },
                        "note": "Approve all C10 files.",
                    }
                ),
                config=config,
            )

            self.assertIn("__interrupt__", fifth)

            fifth_interrupt = fifth[
                "__interrupt__"
            ][0].value

            self.assertEqual(
                fifth_interrupt["type"],
                "dft_execution_options_required",
            )
            self.assertEqual(
                fifth_interrupt["job_source"],
                "c10_slab",
            )

            sixth = graph.invoke(
                Command(
                    resume={"mode": "relax_only"}
                ),
                config=config,
            )

            self.assertIn("__interrupt__", sixth)

            sixth_interrupt = sixth[
                "__interrupt__"
            ][0].value

            self.assertEqual(
                sixth_interrupt["type"],
                "remote_upload_review_required",
            )
            self.assertEqual(
                sixth_interrupt["plan_digest"],
                "test-plan-digest",
            )

            seventh = graph.invoke(
                Command(
                    resume={
                        "action": "approve_upload",
                        "approved_job_ids": [
                            "C1-fcc-01-slab111"
                        ],
                        "plan_digest": "test-plan-digest",
                        "confirmation_text": (
                            "UPLOAD c4-double-interrupt"
                        ),
                        "note": "Approve test upload.",
                    }
                ),
                config=config,
            )

            self.assertIn("__interrupt__", seventh)

            seventh_interrupt = seventh[
                "__interrupt__"
            ][0].value

            self.assertEqual(
                seventh_interrupt["type"],
                "remote_submission_review_required",
            )
            self.assertEqual(
                seventh_interrupt["plan_digest"],
                "test-plan-digest",
            )
            self.assertEqual(
                seventh_interrupt["confirmation_phrase"],
                "SUBMIT c4-double-interrupt",
            )

            final = graph.invoke(
                Command(
                    resume={
                        "action": "approve_submission",
                        "approved_job_ids": [
                            "C1-fcc-01-slab111"
                        ],
                        "plan_digest": "test-plan-digest",
                        "confirmation_text": (
                            "SUBMIT c4-double-interrupt"
                        ),
                        "note": "Approve mocked submission.",
                    }
                ),
                config=config,
            )

        self.assertNotIn("__interrupt__", final)
        self.assertEqual(
            final["status"],
            "submission_jobs_recorded",
        )
        self.assertEqual(
            final["candidate_review"]["selected_count"],
            1,
        )
        self.assertTrue(
            final["candidate_review"][
                "ready_for_structure_modeling"
            ]
        )
        self.assertEqual(
            final["selected_candidates"][0]["candidate_id"],
            "C1",
        )
        self.assertEqual(
            final["literature_review"]["accepted_count"],
            1,
        )
        self.assertEqual(
            final["candidate_generation"]["candidate_count"],
            2,
        )
        self.assertEqual(
            final["structure_modeling"]["structure_count"],
            1,
        )
        self.assertEqual(
            final["bulk_structures"][0]["atom_count"],
            32,
        )
        self.assertEqual(
            final["formation_energy_evaluation"][
                "cgcnn_predicted_count"
            ],
            1,
        )
        self.assertAlmostEqual(
            final["formation_energy_structures"][0][
                "formation_energy"
            ],
            0.03,
        )
        self.assertEqual(
            final["stability_screening"]["passed_count"],
            1,
        )
        self.assertTrue(
            final["slab_eligible_structures"][0][
                "eligible_for_slab"
            ]
        )
        self.assertEqual(
            final["generated_slabs"][0]["atom_count"],
            48,
        )
        self.assertEqual(
            final["generated_slabs"][0][
                "vacuum_angstrom"
            ],
            18.0,
        )
        self.assertEqual(
            final["slab_quality"]["passed_count"],
            1,
        )
        self.assertEqual(
            len(final["dft_approved_slabs"]),
            1,
        )
        self.assertEqual(
            final["dft_approved_slabs"][0][
                "atom_count"
            ],
            48,
        )
        self.assertEqual(len(final["dft_jobs"]), 1)
        self.assertEqual(
            final["dft_jobs"][0]["file_count"],
            5,
        )
        self.assertTrue(
            final["dft_jobs"][0]["submission_ready"]
        )
        self.assertEqual(
            final["dft_execution_options"]["mode"],
            "relax_only",
        )
        self.assertEqual(
            final["dft_local_preflight"]["passed_count"],
            1,
        )
        self.assertEqual(
            final["cluster_readonly_preflight"][
                "passed_count"
            ],
            1,
        )
        self.assertFalse(
            final["cluster_readonly_preflight"][
                "upload_performed"
            ]
        )
        self.assertFalse(
            final["cluster_readonly_preflight"][
                "remote_write_performed"
            ]
        )
        self.assertFalse(
            final["cluster_readonly_preflight"][
                "submission_performed"
            ]
        )
        self.assertEqual(
            final["remote_execution_plan"][
                "plan_digest"
            ],
            "test-plan-digest",
        )
        self.assertEqual(
            final["remote_upload_result"][
                "verified_count"
            ],
            1,
        )
        self.assertEqual(
            len(final["remote_verified_jobs"]),
            1,
        )
        self.assertFalse(
            final["remote_upload_result"][
                "submission_performed"
            ]
        )
        self.assertEqual(
            final["remote_submission_result"][
                "submitted_count"
            ],
            1,
        )
        self.assertEqual(
            final["submitted_dft_jobs"][0][
                "slurm_job_id"
            ],
            "123456",
        )
        self.assertEqual(
            final["submission_recording"]["recorded_count"],
            1,
        )
        self.assertEqual(
            final["persisted_cluster_jobs"][0]["slurm_job_id"],
            "123456",
        )

    def test_no_candidate_selection_is_recorded_cleanly(self):
        with (
            patch.dict(
                os.environ,
                {"LLM_ENABLED": "false"},
            ),
            patch.object(
                nodes.services.candidate_generator,
                "generate_and_score",
                return_value=generation_result(),
            ),
        ):
            from app.graph.workflow import build_graph

            graph = build_graph()
            config = {
                "configurable": {
                    "thread_id": "c4-no-selection",
                }
            }

            first = graph.invoke(
                {
                    "task_id": "c4-no-selection",
                    "question": (
                        "不检索文献，设计 HER "
                        "高熵合金催化剂"
                    ),
                    "errors": [],
                    "warnings": [],
                    "retry_count": 0,
                    "status": "created",
                },
                config=config,
            )

            self.assertIn("__interrupt__", first)
            interrupt_value = first[
                "__interrupt__"
            ][0].value
            self.assertEqual(
                interrupt_value["type"],
                "candidate_review_required",
            )

            final = graph.invoke(
                Command(
                    resume={
                        "select": [],
                        "reject": [],
                        "defer": ["C1", "C2"],
                        "note": "No candidate selected.",
                    }
                ),
                config=config,
            )

        self.assertEqual(
            final["status"],
            "dft_execution_options_skipped",
        )
        self.assertEqual(final["selected_candidates"], [])
        self.assertFalse(
            final["candidate_review"][
                "ready_for_structure_modeling"
            ]
        )

    def test_oer_without_evidence_skips_candidate_review(self):
        with patch.dict(
            os.environ,
            {"LLM_ENABLED": "false"},
        ):
            from app.graph.workflow import build_graph

            graph = build_graph()
            result = graph.invoke(
                {
                    "task_id": "c4-oer-no-evidence",
                    "question": (
                        "不检索文献，设计 OER "
                        "高熵合金催化剂"
                    ),
                    "errors": [],
                    "warnings": [],
                    "retry_count": 0,
                    "status": "created",
                },
                config={
                    "configurable": {
                        "thread_id": "c4-oer-no-evidence",
                    }
                },
            )

        self.assertNotIn("__interrupt__", result)
        self.assertEqual(
            result["c_stage_capability"]["generation_mode"],
            "waiting_for_evidence",
        )
        self.assertEqual(
            result["candidate_generation"]["candidate_count"],
            0,
        )
        self.assertEqual(
            result["candidate_review"]["status"],
            "candidate_review_skipped",
        )
        self.assertEqual(result["selected_candidates"], [])
        self.assertEqual(
            result["status"],
            "dft_execution_options_skipped",
        )


if __name__ == "__main__":
    unittest.main()
