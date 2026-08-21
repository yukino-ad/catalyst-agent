import unittest
from unittest.mock import patch

from app.graph import nodes
from app.graph.routes import (
    route_after_cluster_readonly_preflight,
)


class GraphRemoteExecutionPlanTest(unittest.TestCase):
    def test_passed_cluster_preflight_routes_to_plan(self):
        route = route_after_cluster_readonly_preflight({
            "cluster_readonly_preflight": {
                "status": (
                    "cluster_readonly_preflight_passed"
                ),
            },
            "cluster_preflight_jobs": [{
                "job_id": "S1",
            }],
        })

        self.assertEqual(route, "remote_plan")

    def test_failed_cluster_preflight_routes_to_end(self):
        route = route_after_cluster_readonly_preflight({
            "cluster_readonly_preflight": {
                "status": (
                    "cluster_readonly_preflight_failed"
                ),
            },
            "cluster_preflight_jobs": [{
                "job_id": "S1",
            }],
        })

        self.assertEqual(route, "end")

    def test_empty_jobs_route_to_end(self):
        route = route_after_cluster_readonly_preflight({
            "cluster_readonly_preflight": {
                "status": (
                    "cluster_readonly_preflight_passed"
                ),
            },
            "cluster_preflight_jobs": [],
        })

        self.assertEqual(route, "end")

    def test_node_exposes_remote_plan(self):
        service_result = {
            "status": "remote_execution_plan_ready",
            "job_count": 1,
            "jobs": [{"job_id": "S1"}],
            "remote_write_performed": False,
            "upload_performed": False,
            "submission_performed": False,
        }

        with patch.object(
            nodes.services.remote_execution_plan_service,
            "plan",
            return_value=service_result,
        ) as mocked_plan:
            result = nodes.remote_execution_plan_node({
                "task_id": "task-01",
                "dft_job_source": "c10_slab",
                "cluster_preflight_jobs": [{
                    "job_id": "S1",
                }],
                "errors": [],
            })

        self.assertEqual(
            result["status"],
            "remote_execution_plan_ready",
        )
        self.assertEqual(
            result["remote_execution_plan"],
            service_result,
        )
        mocked_plan.assert_called_once_with(
            jobs=[{"job_id": "S1"}],
            task_id="task-01",
            job_source="c10_slab",
        )

    def test_node_records_service_error(self):
        with patch.object(
            nodes.services.remote_execution_plan_service,
            "plan",
            side_effect=ValueError("unsafe plan"),
        ):
            result = nodes.remote_execution_plan_node({
                "task_id": "task-01",
                "dft_job_source": "c10_slab",
                "cluster_preflight_jobs": [{
                    "job_id": "S1",
                }],
                "errors": [],
            })

        self.assertEqual(
            result["status"],
            "remote_execution_plan_failed",
        )
        self.assertTrue(result["errors"])
        self.assertFalse(
            result["remote_execution_plan"][
                "remote_write_performed"
            ]
        )


if __name__ == "__main__":
    unittest.main()
