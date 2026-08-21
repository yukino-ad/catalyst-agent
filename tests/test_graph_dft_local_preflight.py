import unittest
from unittest.mock import patch

from app.graph import nodes
from app.graph.routes import (
    route_after_dft_local_preflight,
)


class GraphDFTLocalPreflightTest(unittest.TestCase):
    def test_passed_result_exposes_eligible_jobs(self):
        service_result = {
            "status": "dft_local_preflight_passed",
            "job_count": 1,
            "passed_count": 1,
            "failed_count": 0,
            "jobs": [{"job_id": "B1"}],
            "eligible_jobs": [{"job_id": "B1"}],
        }

        with patch.object(
            nodes.services.dft_local_preflight_service,
            "inspect",
            return_value=service_result,
        ):
            result = nodes.dft_local_preflight_node({
                "dft_preflight_jobs": [{"job_id": "B1"}],
                "dft_job_source": "c6d_bulk_formation",
                "bulk_dft_input_preview": {
                    "bundles": [],
                },
                "warnings": [],
            })

        self.assertEqual(
            result["status"],
            "dft_local_preflight_passed",
        )
        self.assertEqual(
            result["dft_local_preflight_jobs"],
            [{"job_id": "B1"}],
        )

    def test_passed_routes_to_cluster_preflight(self):
        route = route_after_dft_local_preflight({
            "dft_local_preflight": {
                "status": "dft_local_preflight_passed",
                "job_count": 1,
            }
        })
        self.assertEqual(route, "cluster_preflight")

    def test_failed_routes_to_end(self):
        route = route_after_dft_local_preflight({
            "dft_local_preflight": {
                "status": "dft_local_preflight_failed",
                "job_count": 1,
            }
        })
        self.assertEqual(route, "end")


if __name__ == "__main__":
    unittest.main()