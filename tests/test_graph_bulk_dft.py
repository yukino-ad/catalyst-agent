import unittest
from unittest.mock import patch

from app.graph import nodes
from app.graph.routes import (
    route_after_bulk_dft_review,
    route_after_formation_energy,
)


class GraphBulkDFTTest(unittest.TestCase):
    def test_dft_queue_enters_c6d(self):
        self.assertEqual(
            route_after_formation_energy({
                "c_stage_execution_mode": "dft_validation",
                "dft_formation_energy_queue": [{"structure_id": "S1"}]
            }),
            "bulk_dft",
        )

    def test_empty_queue_enters_c7(self):
        self.assertEqual(
            route_after_formation_energy({
                "c_stage_execution_mode": "stability_screening",
                "dft_formation_energy_queue": []
            }),
            "stability",
        )

    def test_revision_route_loops_back(self):
        self.assertEqual(
            route_after_bulk_dft_review({
                "bulk_dft_input_review": {"action": "revise"}
            }),
            "revise",
        )
        self.assertEqual(
            route_after_bulk_dft_review({
                "bulk_dft_input_review": {"action": "finalize"}
            }),
            "finalize",
        )

    def test_preview_exposes_service_result(self):
        service_result = {
            "status": "bulk_dft_input_preview_completed",
            "bundle_count": 1,
            "bundles": [{"bundle_id": "S1"}],
        }
        with patch.object(
            nodes.services.bulk_dft_input_bundle_service,
            "preview",
            return_value=service_result,
        ):
            result = nodes.bulk_dft_input_preview_node({
                "task_id": "test",
                "dft_formation_energy_queue": [{"structure_id": "S1"}],
            })
        self.assertEqual(
            result["status"],
            "bulk_dft_input_preview_completed",
        )

    def test_empty_review_is_skipped(self):
        result = nodes.bulk_dft_input_review_node({
            "bulk_dft_input_preview": {"bundles": []}
        })
        self.assertEqual(
            result["status"],
            "bulk_dft_input_review_skipped",
        )

    def test_revision_apply_updates_c6d_state(self):
        service_result = {
            "preview": {"bundles": [{"bundle_id": "S1"}]},
            "validation": {"status": "bulk_dft_revision_accepted"},
            "history": [{"bundle_id": "S1"}],
            "revision_count": 1,
        }
        with patch.object(
            nodes.services.bulk_dft_input_revision_service,
            "apply",
            return_value=service_result,
        ):
            result = nodes.bulk_dft_revision_apply_node({
                "bulk_dft_input_preview": {"bundles": []},
                "bulk_dft_revision_plan": {"plans": [{}]},
            })
        self.assertEqual(
            result["status"],
            "bulk_dft_revision_accepted",
        )
        self.assertEqual(result["bulk_dft_revision_count"], 1)

    def test_finalize_exposes_bulk_jobs(self):
        service_result = {
            "status": "dft_input_preparation_completed",
            "prepared_job_count": 1,
            "jobs": [{"job_id": "S1", "file_count": 5}],
            "failures": [],
        }
        with patch.object(
            nodes.services.bulk_dft_input_bundle_service,
            "finalize",
            return_value=service_result,
        ):
            result = nodes.bulk_dft_input_finalize_node({
                "bulk_dft_input_preview": {},
                "bulk_dft_input_review": {},
            })
        self.assertEqual(
            result["status"],
            "bulk_dft_input_preparation_completed",
        )
        self.assertEqual(result["bulk_dft_jobs"][0]["file_count"], 5)


if __name__ == "__main__":
    unittest.main()
