from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.domain.workflow_run_repository import (
    WorkflowRunRepository,
)
from app.workflow_resume_cli import (
    ADSORPTION_ENERGY_STAGE,
    ADSORPTION_MONITORING_STAGE,
    ADSORPTION_SUBMISSION_STAGE,
    JOB_OPERATION_STAGES,
    _adsorption_energy_state,
    _job_ids,
    _submission_state,
    load_workflow,
    main,
    resolve_resume_target,
    resume_workflow,
)


class WorkflowResumeCliTest(unittest.TestCase):
    def test_job_operations_auto_hands_off_to_c12_6(self):
        workflow = {
            "task_id": "task-handoff",
            "resume_stage": "c12.1_adsorption_planning",
            "active_slurm_jobs": ["123456"],
            "terminal": False,
        }
        latest = {
            "task_id": "task-handoff",
            "resume_stage": ADSORPTION_SUBMISSION_STAGE,
            "adsorption_dft_jobs": [{"job_id": "A1"}],
            "adsorption_dft_input_preview": {"bundles": [{"bundle_id": "A1"}]},
            "terminal": False,
        }
        with patch(
            "app.workflow_resume_cli.job_operations_graph.invoke",
            return_value={"status": "dft_input_preparation_completed"},
        ), patch(
            "app.workflow_resume_cli.WorkflowRunRepository.get",
            return_value=latest,
        ), patch(
            "app.workflow_resume_cli.adsorption_execution_graph.invoke",
            return_value={"status": "adsorption_submission_deferred"},
        ) as execution:
            result = resume_workflow(workflow, "handoff-thread")

        self.assertEqual(result["status"], "adsorption_submission_deferred")
        execution.assert_called_once()

    def test_c12_7_routes_to_adsorption_energy(self):
        result = resolve_resume_target({
            "terminal": False,
            "resume_stage": ADSORPTION_ENERGY_STAGE,
        })

        self.assertEqual(result, "adsorption_energy")

    def test_c12_7_state_restores_three_energy_inputs(self):
        workflow = {
            "task_id": "task-c12-7",
            "adsorption_parsed_results": [{
                "job_source": "c12_5_adsorption",
                "scientific_identity": {
                    "adsorption_structure_id": "A-CO-001",
                    "source_clean_slab_id": "S1",
                    "adsorbate": "CO",
                },
                "parsed_vasp_result": {
                    "final_toten_ev": -296.0,
                },
            }],
            "clean_slab_energies": {"S1": -281.0},
            "reference_energies": {"CO": -14.0},
        }

        state = _adsorption_energy_state(workflow)

        self.assertEqual(state["task_id"], "task-c12-7")
        self.assertEqual(
            state["clean_slab_energies"]["S1"],
            -281.0,
        )
        self.assertEqual(
            state["reference_energies"]["CO"],
            -14.0,
        )

    def test_c12_7_resume_rejects_missing_reference(self):
        workflow = {
            "task_id": "task-c12-7",
            "adsorption_parsed_results": [{
                "scientific_identity": {
                    "adsorption_structure_id": "A-CO-001",
                    "source_clean_slab_id": "S1",
                    "adsorbate": "CO",
                },
            }],
            "clean_slab_energies": {"S1": -281.0},
            "reference_energies": {},
        }

        with self.assertRaisesRegex(
            ValueError,
            "Missing reference energies: CO",
        ):
            _adsorption_energy_state(workflow)

    def test_valid_task_id_can_be_loaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = WorkflowRunRepository(Path(temporary))
            repository.update(
                "task-001",
                {
                    "workflow_status": "waiting",
                    "resume_stage": "c12.1_adsorption_planning",
                },
            )

            result = load_workflow(
                "task-001",
                repository=repository,
            )

            self.assertEqual(result["task_id"], "task-001")
            self.assertEqual(
                result["resume_stage"],
                "c12.1_adsorption_planning",
            )

    def test_missing_workflow_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = WorkflowRunRepository(Path(temporary))

            with self.assertRaises(FileNotFoundError):
                load_workflow(
                    "missing-task",
                    repository=repository,
                )

    def test_unsafe_task_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = WorkflowRunRepository(Path(temporary))

            invalid_task_ids = [
                "../secret",
                "task/name",
                "task name",
                "task\\name",
                "",
            ]

            for task_id in invalid_task_ids:
                with self.subTest(task_id=task_id):
                    with self.assertRaises(ValueError):
                        load_workflow(
                            task_id,
                            repository=repository,
                        )

    def test_resume_stages_route_to_expected_graphs(self):
        for stage in JOB_OPERATION_STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(
                    resolve_resume_target(
                        {
                            "terminal": False,
                            "resume_stage": stage,
                        }
                    ),
                    "job_operations",
                )

        self.assertEqual(
            resolve_resume_target(
                {
                    "terminal": False,
                    "resume_stage": ADSORPTION_SUBMISSION_STAGE,
                }
            ),
            "adsorption_submission",
        )

        self.assertEqual(
            resolve_resume_target(
                {
                    "terminal": False,
                    "resume_stage": ADSORPTION_MONITORING_STAGE,
                }
            ),
            "adsorption_monitoring",
        )

    def test_terminal_workflow_routes_to_complete(self):
        result = resolve_resume_target(
            {
                "terminal": True,
                "resume_stage": "c12.1_adsorption_planning",
            }
        )

        self.assertEqual(result, "complete")

    def test_slurm_job_ids_must_be_numeric(self):
        with self.assertRaises(ValueError):
            _job_ids(
                {
                    "active_slurm_jobs": [
                        "123456",
                        "invalid-job-id",
                    ]
                }
            )

        self.assertEqual(
            _job_ids(
                {
                    "active_slurm_jobs": [
                        "123456",
                        "123456",
                        "789012",
                    ]
                }
            ),
            ["123456", "789012"],
        )

    def test_c12_submission_requires_jobs_and_preview(self):
        base_workflow = {
            "task_id": "task-c12",
            "task_context": {},
        }

        with self.assertRaises(ValueError):
            _submission_state(base_workflow)

        with self.assertRaises(ValueError):
            _submission_state(
                {
                    **base_workflow,
                    "adsorption_dft_jobs": [
                        {"job_id": "ads-001"}
                    ],
                }
            )

        result = _submission_state(
            {
                **base_workflow,
                "adsorption_dft_jobs": [
                    {"job_id": "ads-001"}
                ],
                "adsorption_dft_input_preview": {
                    "bundles": [
                        {"bundle_id": "bundle-001"}
                    ]
                },
            }
        )

        self.assertEqual(result["task_id"], "task-c12")
        self.assertEqual(
            len(result["adsorption_dft_jobs"]),
            1,
        )
        self.assertEqual(
            result["status"],
            "workflow_resume_created",
        )

    def test_show_only_does_not_run_graph(self):
        workflow = {
            "task_id": "task-show-only",
            "workflow_status": "waiting",
            "resume_stage": "c12.1_adsorption_planning",
            "active_slurm_jobs": ["123456"],
            "terminal": False,
        }

        with patch(
            "app.workflow_resume_cli.load_workflow",
            return_value=workflow,
        ), patch(
            "app.workflow_resume_cli.resume_workflow",
        ) as mocked_resume, patch.object(
            sys,
            "argv",
            [
                "workflow_resume_cli",
                "task-show-only",
                "--show-only",
            ],
        ), redirect_stdout(io.StringIO()) as output:
            main()

        mocked_resume.assert_not_called()
        self.assertIn(
            "workflow_resume_plan",
            output.getvalue(),
        )
        self.assertIn(
            "job_operations",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
