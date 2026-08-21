import unittest
from unittest.mock import patch

from app.graph import nodes
from app.graph.routes import (
    route_after_remote_submission_review,
    route_after_remote_upload,
)


def verified_state() -> dict:
    return {
        "remote_execution_plan": {
            "status": "remote_execution_plan_ready",
            "task_id": "task-01",
            "plan_digest": "digest",
        },
        "remote_upload_result": {
            "status": "remote_upload_verified",
        },
        "remote_verified_jobs": [{
            "job_id": "S1",
            "remote_job_directory": (
                "/work/runs/task-01/S1"
            ),
            "remote_hash_verified": True,
        }],
    }


class GraphRemoteSubmissionTest(unittest.TestCase):
    def test_verified_upload_routes_to_review(self):
        self.assertEqual(
            route_after_remote_upload(verified_state()),
            "submission_review",
        )

    def test_partial_upload_routes_to_end(self):
        state = verified_state()
        state["remote_upload_result"]["status"] = (
            "remote_upload_partial"
        )

        self.assertEqual(
            route_after_remote_upload(state),
            "end",
        )

    def test_empty_verified_jobs_routes_to_end(self):
        state = verified_state()
        state["remote_verified_jobs"] = []

        self.assertEqual(
            route_after_remote_upload(state),
            "end",
        )

    def test_approved_review_routes_to_submit(self):
        self.assertEqual(
            route_after_remote_submission_review({
                "remote_submission_review": {
                    "status": "remote_submission_approved",
                    "approved_job_ids": ["S1"],
                },
            }),
            "submit",
        )

    def test_deferred_review_routes_to_end(self):
        self.assertEqual(
            route_after_remote_submission_review({
                "remote_submission_review": {
                    "status": "remote_submission_deferred",
                    "approved_job_ids": [],
                },
            }),
            "end",
        )

    def test_review_interrupt_exposes_digest_and_phrase(self):
        with patch(
            "app.graph.nodes.interrupt",
            return_value={
                "action": "approve_submission",
                "approved_job_ids": ["S1"],
                "plan_digest": "digest",
                "confirmation_text": "SUBMIT task-01",
                "note": "approved",
            },
        ) as mocked_interrupt:
            result = nodes.remote_submission_review_node(
                verified_state()
            )

        request = mocked_interrupt.call_args.args[0]
        self.assertEqual(
            request["type"],
            "remote_submission_review_required",
        )
        self.assertEqual(request["plan_digest"], "digest")
        self.assertEqual(
            request["confirmation_phrase"],
            "SUBMIT task-01",
        )
        self.assertEqual(
            result["status"],
            "remote_submission_approved",
        )

    def test_unverified_state_skips_review(self):
        result = nodes.remote_submission_review_node({
            "remote_upload_result": {
                "status": "remote_upload_failed",
            },
            "remote_verified_jobs": [],
        })

        self.assertEqual(
            result["status"],
            "remote_submission_review_skipped",
        )

    def test_submission_result_exposes_submitted_jobs(self):
        service_result = {
            "status": "remote_submission_completed",
            "submitted_jobs": [{
                "job_id": "S1",
                "slurm_job_id": "123456",
            }],
        }

        with patch.object(
            nodes.services.remote_submission_service,
            "submit",
            return_value=service_result,
        ):
            result = nodes.remote_submission_node({
                **verified_state(),
                "remote_submission_review": {
                    "status": "remote_submission_approved",
                },
            })

        self.assertEqual(
            result["status"],
            "remote_submission_completed",
        )
        self.assertEqual(
            result["submitted_dft_jobs"][0][
                "slurm_job_id"
            ],
            "123456",
        )

    def test_submission_service_error_is_recorded(self):
        with patch.object(
            nodes.services.remote_submission_service,
            "submit",
            side_effect=ValueError("submission failed"),
        ):
            result = nodes.remote_submission_node({
                **verified_state(),
                "remote_submission_review": {
                    "status": "remote_submission_approved",
                },
                "errors": [],
            })

        self.assertEqual(
            result["status"],
            "remote_submission_failed",
        )
        self.assertTrue(result["errors"])
        self.assertFalse(
            result["remote_submission_result"][
                "submission_performed"
            ]
        )


if __name__ == "__main__":
    unittest.main()
