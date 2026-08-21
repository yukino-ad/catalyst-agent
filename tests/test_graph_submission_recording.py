import unittest
from unittest.mock import patch

from app.graph import nodes


class GraphSubmissionRecordingTest(unittest.TestCase):
    def test_records_submitted_jobs(self):
        service_result = {
            "status": "submission_jobs_recorded",
            "records": [{"slurm_job_id": "123456"}],
        }
        with patch.object(
            nodes.services.submitted_job_repository,
            "record_submission",
            return_value=service_result,
        ):
            result = nodes.submission_record_node({
                "task_id": "task-01",
                "remote_execution_plan": {
                    "job_source": "c10_slab",
                    "plan_digest": "digest",
                },
                "submitted_dft_jobs": [{"slurm_job_id": "123456"}],
            })
        self.assertEqual(result["persisted_cluster_jobs"], service_result["records"])

    def test_repository_error_is_recorded(self):
        with patch.object(
            nodes.services.submitted_job_repository,
            "record_submission",
            side_effect=ValueError("failed"),
        ):
            result = nodes.submission_record_node({
                "submitted_dft_jobs": [], "errors": [],
            })
        self.assertEqual(result["status"], "submission_recording_failed")
        self.assertTrue(result["errors"])


if __name__ == "__main__":
    unittest.main()
