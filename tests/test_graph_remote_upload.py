import unittest
from unittest.mock import patch

from app.graph import nodes
from app.graph.routes import (
    route_after_remote_execution_plan,
    route_after_remote_upload_review,
)


def ready_plan() -> dict:
    return {
        "status": "remote_execution_plan_ready",
        "task_id": "task-01",
        "plan_digest": "digest",
        "remote_batch_directory": "/work/runs/task-01",
        "job_count": 1,
        "jobs": [{
            "job_id": "S1",
            "remote_job_directory": (
                "/work/runs/task-01/S1"
            ),
            "files": [],
        }],
    }


class GraphRemoteUploadTest(unittest.TestCase):
    def test_ready_plan_routes_to_upload_review(self):
        self.assertEqual(
            route_after_remote_execution_plan({
                "remote_execution_plan": ready_plan(),
            }),
            "upload_review",
        )

    def test_failed_plan_routes_to_end(self):
        self.assertEqual(
            route_after_remote_execution_plan({
                "remote_execution_plan": {
                    "status": (
                        "remote_execution_plan_failed"
                    ),
                },
            }),
            "end",
        )

    def test_approved_review_routes_to_upload(self):
        self.assertEqual(
            route_after_remote_upload_review({
                "remote_upload_review": {
                    "status": "remote_upload_approved",
                    "approved_job_ids": ["S1"],
                },
            }),
            "upload",
        )

    def test_deferred_review_routes_to_end(self):
        self.assertEqual(
            route_after_remote_upload_review({
                "remote_upload_review": {
                    "status": "remote_upload_deferred",
                    "approved_job_ids": [],
                },
            }),
            "end",
        )

    def test_review_interrupt_exposes_digest(self):
        with patch(
            "app.graph.nodes.interrupt",
            return_value={
                "action": "approve_upload",
                "approved_job_ids": ["S1"],
                "plan_digest": "digest",
                "confirmation_text": "UPLOAD task-01",
                "note": "approved",
            },
        ) as mocked_interrupt:
            result = nodes.remote_upload_review_node({
                "remote_execution_plan": ready_plan(),
            })

        request = mocked_interrupt.call_args.args[0]
        self.assertEqual(
            request["type"],
            "remote_upload_review_required",
        )
        self.assertEqual(
            request["plan_digest"],
            "digest",
        )
        self.assertEqual(
            result["remote_upload_review"]["status"],
            "remote_upload_approved",
        )

    def test_upload_result_exposes_verified_jobs(self):
        service_result = {
            "status": "remote_upload_verified",
            "verified_jobs": [{"job_id": "S1"}],
            "submission_performed": False,
        }

        with patch.object(
            nodes.services.remote_upload_service,
            "upload",
            return_value=service_result,
        ):
            result = nodes.remote_upload_node({
                "remote_execution_plan": ready_plan(),
                "remote_upload_review": {
                    "status": "remote_upload_approved",
                },
            })

        self.assertEqual(
            result["remote_verified_jobs"],
            [{"job_id": "S1"}],
        )
        self.assertEqual(
            result["status"],
            "remote_upload_verified",
        )

    def test_upload_service_error_is_recorded(self):
        with patch.object(
            nodes.services.remote_upload_service,
            "upload",
            side_effect=ValueError("upload failed"),
        ):
            result = nodes.remote_upload_node({
                "remote_execution_plan": ready_plan(),
                "remote_upload_review": {
                    "status": "remote_upload_approved",
                },
                "errors": [],
            })

        self.assertEqual(
            result["status"],
            "remote_upload_failed",
        )
        self.assertTrue(result["errors"])
        self.assertFalse(
            result["remote_upload_result"][
                "submission_performed"
            ]
        )


if __name__ == "__main__":
    unittest.main()
