import unittest
from unittest.mock import patch

from app.graph import nodes
from app.graph.adsorption_execution_workflow import (
    build_adsorption_execution_graph,
)


class GraphAdsorptionExecutionTest(unittest.TestCase):
    def test_relax_only_exposes_adsorption_jobs(self):
        jobs = [{
            "job_id": "A1",
            "adsorption_structure_id": "A1",
            "job_dir": "data/adsorption_dft_inputs/task/A1",
        }]
        with patch(
            "app.graph.nodes.interrupt",
            return_value={"mode": "relax_only"},
        ):
            result = nodes.adsorption_dft_execution_options_node({
                "adsorption_dft_jobs": jobs,
            })
        self.assertEqual(result["dft_job_source"], "c12_5_adsorption")
        self.assertEqual(result["dft_preflight_jobs"], jobs)
        self.assertEqual(
            result["dft_execution_options"]["energy_source"],
            "relax",
        )

    def test_static_mode_is_rejected(self):
        with patch(
            "app.graph.nodes.interrupt",
            return_value={"mode": "relax_then_static"},
        ):
            with self.assertRaisesRegex(ValueError, "relax_only"):
                nodes.adsorption_dft_execution_options_node({
                    "adsorption_dft_jobs": [{"job_id": "A1"}],
                })

    def test_defer_does_not_expose_preflight_jobs(self):
        with patch(
            "app.graph.nodes.interrupt",
            return_value={"mode": "defer"},
        ):
            result = nodes.adsorption_dft_execution_options_node({
                "adsorption_dft_jobs": [{"job_id": "A1"}],
            })
        self.assertEqual(result["dft_preflight_jobs"], [])
        self.assertEqual(result["dft_job_source"], "")

    def test_local_preflight_uses_adsorption_preview(self):
        preview = {"bundles": [{"bundle_id": "A1"}]}
        with patch.object(
            nodes.services.dft_local_preflight_service,
            "inspect",
            return_value={
                "status": "dft_local_preflight_passed",
                "failed_count": 0,
                "eligible_jobs": [{"job_id": "A1"}],
            },
        ) as mocked:
            nodes.dft_local_preflight_node({
                "dft_preflight_jobs": [{"job_id": "A1"}],
                "dft_job_source": "c12_5_adsorption",
                "adsorption_dft_input_preview": preview,
                "warnings": [],
            })
        mocked.assert_called_once_with(
            jobs=[{"job_id": "A1"}],
            preview=preview,
            job_source="c12_5_adsorption",
        )

    def test_submission_record_uses_adsorption_resume_stage(self):
        with patch.object(
            nodes.services.submitted_job_repository,
            "record_submission",
            return_value={
                "status": "submission_jobs_recorded",
                "records": [{"slurm_job_id": "123456"}],
            },
        ), patch(
            "app.domain.workflow_run_repository."
            "WorkflowRunRepository.update",
            return_value={"task_id": "T1"},
        ) as mocked_update:
            nodes.submission_record_node({
                "task_id": "T1",
                "remote_execution_plan": {
                    "job_source": "c12_5_adsorption",
                    "plan_digest": "digest",
                },
                "submitted_dft_jobs": [{"slurm_job_id": "123456"}],
            })
        changes = mocked_update.call_args.args[1]
        self.assertEqual(
            changes["resume_stage"],
            "c12.6_adsorption_result_monitoring",
        )

    def test_submission_graph_has_two_human_review_nodes(self):
        graph = build_adsorption_execution_graph().get_graph()
        names = set(graph.nodes)
        self.assertIn("remote_upload_review", names)
        self.assertIn("remote_submission_review", names)
        self.assertIn("submission_record", names)

    def test_submission_graph_has_no_monitoring_or_retry(self):
        names = set(build_adsorption_execution_graph().get_graph().nodes)
        self.assertNotIn("monitor", names)
        self.assertNotIn("retry_review", names)


if __name__ == "__main__":
    unittest.main()
