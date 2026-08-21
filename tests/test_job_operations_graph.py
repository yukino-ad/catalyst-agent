import unittest
from unittest.mock import patch

from app.graph import job_operations


class JobOperationsGraphTest(unittest.TestCase):
    def test_download_review_interrupt_is_bound_to_jobs(self):
        state = {
            "completion_result": {
                "jobs": [{
                    "slurm_job_id": "123456",
                    "job_id": "S1",
                    "download_eligible": True,
                    "scheduler_state": "COMPLETED",
                    "vasp_decision": "completed_converged",
                    "remote_job_directory": "/work/runs/task/S1",
                }],
            },
        }
        with patch(
            "app.graph.job_operations.interrupt",
            return_value={
                "action": "approve_download",
                "approved_slurm_job_ids": ["123456"],
                "confirmation_text": "DOWNLOAD 123456",
            },
        ) as mocked:
            result = job_operations.download_review_node(state)
        request = mocked.call_args.args[0]
        self.assertEqual(request["confirmation_phrase"], "DOWNLOAD 123456")
        self.assertEqual(result["status"], "result_download_approved")

    def test_retry_review_records_plan_without_submission(self):
        job = {
            "slurm_job_id": "123456",
            "job_id": "S1",
            "retry_plan": {
                "eligible": True,
                "required_confirmation": "RETRY 123456",
            },
            "failure_diagnosis": {"category": "walltime"},
        }
        with (
            patch(
                "app.graph.job_operations.interrupt",
                return_value={
                    "decisions": {
                        "123456": {
                            "action": "approve_retry_plan",
                            "confirmation_text": "RETRY 123456",
                        },
                    },
                },
            ),
            patch.object(
                job_operations.services.repository,
                "update",
            ) as mocked_update,
        ):
            result = job_operations.retry_review_node({
                "diagnosis_result": {"jobs": [job]},
            })
        review = result["retry_reviews"][0]
        self.assertEqual(review["status"], "retry_plan_approved")
        self.assertFalse(review["submission_performed"])
        mocked_update.assert_called_once()

    def test_no_download_or_retry_is_skipped(self):
        result = job_operations.download_review_node({
            "completion_result": {"jobs": []},
        })
        self.assertEqual(result["status"], "result_download_review_skipped")
        result = job_operations.retry_review_node({
            "diagnosis_result": {"jobs": []},
        })
        self.assertEqual(result["status"], "retry_review_skipped")


if __name__ == "__main__":
    unittest.main()
