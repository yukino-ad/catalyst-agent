import unittest
from unittest.mock import patch

from app.graph import nodes


class GraphClusterReadonlyPreflightTest(
    unittest.TestCase
):
    def test_passed_result_exposes_jobs(self):
        service_result = {
            "schema_version": "c11.3",
            "status": (
                "cluster_readonly_preflight_passed"
            ),
            "job_count": 1,
            "passed_count": 1,
            "failed_count": 0,
            "jobs": [{"job_id": "S1"}],
            "eligible_jobs": [{"job_id": "S1"}],
            "checks": [],
            "errors": [],
            "upload_performed": False,
            "remote_write_performed": False,
            "submission_performed": False,
        }

        with patch.object(
            nodes.services
            .cluster_readonly_preflight_service,
            "inspect",
            return_value=service_result,
        ):
            result = (
                nodes.cluster_readonly_preflight_node({
                    "dft_local_preflight_jobs": [{
                        "job_id": "S1",
                    }],
                    "warnings": [],
                    "errors": [],
                })
            )

        self.assertEqual(
            result["status"],
            "cluster_readonly_preflight_passed",
        )
        self.assertEqual(
            result["cluster_preflight_jobs"],
            [{"job_id": "S1"}],
        )

    def test_failed_result_blocks_jobs(self):
        service_result = {
            "schema_version": "c11.3",
            "status": (
                "cluster_readonly_preflight_failed"
            ),
            "job_count": 1,
            "passed_count": 0,
            "failed_count": 1,
            "jobs": [{"job_id": "S1"}],
            "eligible_jobs": [],
            "checks": [],
            "errors": [{
                "check": "vasp_executable",
                "message": "VASP is unavailable",
            }],
            "upload_performed": False,
            "remote_write_performed": False,
            "submission_performed": False,
        }

        with patch.object(
            nodes.services
            .cluster_readonly_preflight_service,
            "inspect",
            return_value=service_result,
        ):
            result = (
                nodes.cluster_readonly_preflight_node({
                    "dft_local_preflight_jobs": [{
                        "job_id": "S1",
                    }],
                    "warnings": [],
                    "errors": [],
                })
            )

        self.assertEqual(
            result["cluster_preflight_jobs"],
            [],
        )
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()