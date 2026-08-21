import json
import unittest
from unittest.mock import patch

from app.graph import adsorption_job_operations as operations
from app.graph import job_operations


def record(identifier, source="c12_5_adsorption"):
    return {
        "slurm_job_id": identifier,
        "task_id": "T1",
        "job_id": f"job-{identifier}",
        "job_source": source,
    }


def adsorption_result(identifier="100", adsorbate="CO"):
    return {
        **record(identifier),
        "vasp_decision": "completed_converged",
        "result_parsing_status": "parsed",
        "parsed_vasp_result": {
            "final_toten_ev": -296.0,
        },
        "scientific_identity": {
            "adsorption_structure_id": "A-CO-001",
            "candidate_id": "C1",
            "source_clean_slab_id": "S1",
            "site_id": "site-1",
            "site_type": "ontop",
            "adsorbate": adsorbate,
        },
    }


def clean_slab_result(identifier="200"):
    return {
        **record(identifier, "c10_slab"),
        "vasp_decision": "completed_converged",
        "result_parsing_status": "parsed",
        "parsed_vasp_result": {
            "final_toten_ev": -281.0,
        },
        "scientific_identity": {
            "calculation_type": "clean_slab_relax",
            "slab_id": "S1",
            "candidate_id": "C1",
        },
    }


class AdsorptionJobOperationsTest(unittest.TestCase):
    def test_single_intermediate_gate_selects_exactly_one(self):
        state = {
            "task_id": "T1",
            "adsorption_reaction_plan": {
                "candidate_adsorbates": ["COOH", "CO", "H"],
                "reference_energy_definitions": {
                    "CO": {
                        "reference_expression": "E_CO",
                        "data_version": "reference-v1",
                    }
                },
                "ready_for_site_generation": False,
            },
        }
        with patch(
            "app.graph.job_operations.interrupt",
            return_value={
                "selected_adsorbate": "CO",
                "note": "single CO task",
            },
        ), patch(
            "app.graph.job_operations.WorkflowRunRepository.get",
            return_value={"task_context": {}},
        ), patch(
            "app.graph.job_operations.WorkflowRunRepository.update",
            return_value={"task_id": "T1"},
        ):
            result = job_operations.adsorption_intermediate_review_node(
                state
            )

        self.assertEqual(result["selected_adsorbate"], "CO")
        self.assertEqual(result["planned_adsorbates"], ["CO"])
        self.assertEqual(
            result["adsorption_reaction_plan"]["formal_adsorbates"],
            ["CO"],
        )
        self.assertTrue(
            result["adsorption_reaction_plan"][
                "ready_for_site_generation"
            ]
        )

    def test_single_intermediate_gate_rejects_unknown_choice(self):
        with patch(
            "app.graph.job_operations.interrupt",
            return_value={"selected_adsorbate": "CH4"},
        ):
            with self.assertRaisesRegex(ValueError, "exactly one"):
                job_operations.adsorption_intermediate_review_node({
                    "adsorption_reaction_plan": {
                        "candidate_adsorbates": ["COOH", "CO", "H"],
                    }
                })

    def test_source_filter_selects_only_adsorption_jobs(self):
        values = [
            record("100"),
            record("200", "c6d_bulk_formation"),
            record("300", "c10_slab"),
        ]
        with patch.object(
            operations.services.repository,
            "list_records",
            return_value=values,
        ):
            result = operations.adsorption_source_filter_node({})
        self.assertEqual(result["slurm_job_ids"], ["100"])
        self.assertEqual(result["source_filter"]["job_source"], "c12_5_adsorption")

    def test_requested_ids_still_apply_source_filter(self):
        values = [record("100"), record("200", "c10_slab")]
        with patch.object(
            operations.services.repository,
            "list_records",
            return_value=values,
        ):
            result = operations.adsorption_source_filter_node({
                "requested_slurm_job_ids": ["100", "200"],
            })
        self.assertEqual(result["slurm_job_ids"], ["100"])

    def test_only_converged_parsed_energy_is_ready(self):
        ready = {
            **record("100"),
            "vasp_decision": "completed_converged",
            "result_parsing_status": "parsed",
            "parsed_vasp_result": {"final_toten_ev": -100.0},
        }
        unconverged = {
            **record("101"),
            "vasp_decision": "completed_unconverged",
            "result_parsing_status": "parsed",
            "parsed_vasp_result": {"final_toten_ev": -99.0},
        }
        with patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.update",
            return_value={"task_id": "T1"},
        ):
            result = operations.adsorption_result_ready_node({
                "parse_result": {"jobs": [ready, unconverged]},
                "slurm_job_ids": ["100", "101"],
            })
        self.assertEqual(result["adsorption_result_ready"]["ready_count"], 1)
        self.assertEqual(result["adsorption_parsed_results"][0]["slurm_job_id"], "100")
        self.assertFalse(
            result["adsorption_result_ready"][
                "formation_energy_backfill_performed"
            ]
        )

    def test_missing_energy_is_not_ready(self):
        value = {
            **record("100"),
            "vasp_decision": "completed_converged",
            "result_parsing_status": "parsed",
            "parsed_vasp_result": {"final_toten_ev": None},
        }
        with patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.update",
            return_value={},
        ):
            result = operations.adsorption_result_ready_node({
                "parse_result": {"jobs": [value]},
            })
        self.assertEqual(result["status"], "adsorption_results_not_ready")

    def test_failed_download_stops_before_parser(self):
        state = {
            "download_result": {
                "status": "result_download_failed",
                "jobs": [],
                "errors": [{"message": "connection timed out"}],
            }
        }
        self.assertEqual(operations.route_after_download(state), "end")

    def test_graph_excludes_bulk_backfill_and_structure_nodes(self):
        graph = operations.build_adsorption_job_operations_graph().get_graph()
        names = set(graph.nodes)
        forbidden = {
            "formation_energy_backfill",
            "async_stability_screening",
            "slab_generation",
            "remote_submission",
        }
        self.assertTrue(forbidden.isdisjoint(names))

    def test_graph_contains_c12_7_automatic_chain(self):
        graph = (
            operations
            .build_adsorption_job_operations_graph()
            .get_graph()
        )
        names = set(graph.nodes)
        self.assertIn("adsorption_energy_input", names)
        self.assertIn("adsorption_energy_calculation", names)
        self.assertIn("adsorption_energy_review", names)

        edges = {
            (edge.source, edge.target)
            for edge in graph.edges
        }
        self.assertIn(
            (
                "adsorption_energy_calculation",
                "adsorption_energy_review",
            ),
            edges,
        )
        self.assertIn(
            ("adsorption_energy_review", "__end__"),
            edges,
        )

    def test_energy_input_matches_source_clean_slab_id(self):
        with patch.object(
            operations.services.repository,
            "list_records",
            return_value=[clean_slab_result()],
        ), patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.get",
            return_value={
                "reference_energies": {"CO": -14.0},
            },
        ), patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.update",
            return_value={"task_id": "T1"},
        ):
            result = operations.adsorption_energy_input_node({
                "task_id": "T1",
                "adsorption_parsed_results": [
                    adsorption_result()
                ],
            })

        self.assertEqual(
            result["status"],
            "adsorption_energy_inputs_ready",
        )
        self.assertEqual(
            result["clean_slab_energies"]["S1"][
                "clean_slab_energy_ev"
            ],
            -281.0,
        )
        self.assertEqual(
            operations.route_after_energy_input(result),
            "calculate",
        )

    def test_catalog_reference_energy_is_used_when_not_persisted(self):
        with patch.object(
            operations.services.repository,
            "list_records",
            return_value=[clean_slab_result()],
        ), patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.get",
            return_value={},
        ), patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.update",
            return_value={"task_id": "T1"},
        ):
            result = operations.adsorption_energy_input_node({
                "task_id": "T1",
                "adsorption_parsed_results": [adsorption_result()],
            })

        self.assertEqual(
            result["status"],
            "adsorption_energy_inputs_ready",
        )
        self.assertEqual(
            result["reference_energies"]["CO"][
                "resolved_reference_energy_ev"
            ],
            -14.94164602,
        )
        self.assertEqual(
            result["adsorption_energy_input_preparation"][
                "catalog_resolved_adsorbates"
            ],
            ["CO"],
        )

    def test_missing_reference_energy_stops_before_calculation(self):
        with patch.object(
            operations.services.repository,
            "list_records",
            return_value=[clean_slab_result()],
        ), patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.get",
            return_value={},
        ), patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.update",
            return_value={"task_id": "T1"},
        ):
            result = operations.adsorption_energy_input_node({
                "task_id": "T1",
                "adsorption_parsed_results": [
                    adsorption_result(adsorbate="COOH")
                ],
            })

        self.assertEqual(
            result["status"],
            "adsorption_energy_inputs_required",
        )
        self.assertEqual(
            result["adsorption_energy_input_preparation"][
                "missing_reference_energies"
            ],
            ["COOH"],
        )
        self.assertEqual(
            operations.route_after_energy_input(result),
            "end",
        )

    def test_completed_energy_review_persists_terminal_state(self):
        reviewed = {
            "adsorption_energy_review": {
                "status": "adsorption_energy_review_completed",
                "approved": [{"adsorption_energy_id": "AE-A1"}],
            },
            "approved_adsorption_energies": [
                {"adsorption_energy_id": "AE-A1"}
            ],
            "status": "adsorption_energy_review_completed",
        }
        with patch.object(
            operations,
            "adsorption_energy_review_node",
            return_value=reviewed,
        ), patch(
            "app.graph.adsorption_job_operations."
            "WorkflowRunRepository.update",
            return_value={"task_id": "T1", "terminal": True},
        ) as mocked_update:
            result = (
                operations
                .adsorption_energy_review_and_persist_node({
                    "task_id": "T1",
                    "adsorption_energy_calculation": {
                        "status": "adsorption_energy_calculated"
                    },
                })
            )

        changes = mocked_update.call_args.args[1]
        self.assertTrue(changes["terminal"])
        self.assertIsNone(changes["resume_stage"])
        self.assertEqual(
            result["status"],
            "adsorption_energy_review_completed",
        )

    def test_failure_diagnosis_never_retries_automatically(self):
        failed = {
            **record("100"),
            "scheduler_state": "FAILED",
            "vasp_decision": "failed",
        }
        diagnosis = operations.services.diagnosis._diagnose_one(failed)
        self.assertFalse(diagnosis["automatic_retry_allowed"])
        self.assertEqual(
            diagnosis["retry_plan"]["required_route"],
            "c12.5_revision_then_c12.6_review",
        )

    def test_result_is_json_serializable(self):
        with patch.object(
            operations.services.repository,
            "list_records",
            return_value=[],
        ):
            result = operations.adsorption_source_filter_node({})
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
