import unittest
from unittest.mock import patch

from app.graph import nodes
from app.graph.routes import route_after_dft_input_review


class GraphDFTInputBundleTest(unittest.TestCase):
    def test_review_route_selects_revision_loop(self):
        self.assertEqual(
            route_after_dft_input_review({
                "dft_input_review": {"action": "revise"}
            }),
            "revise",
        )
        self.assertEqual(
            route_after_dft_input_review({
                "dft_input_review": {"action": "finalize"}
            }),
            "finalize",
        )

    def test_preview_exposes_bundle(self):
        service_result = {
            "schema_version": "c10.0",
            "stage": "c10_preview",
            "status": "dft_input_preview_completed",
            "bundle_count": 1,
            "bundles": [{
                "bundle_id": "S1",
                "preview": {},
            }],
        }

        with patch.object(
            nodes.services.vasp_input_bundle_service,
            "preview",
            return_value=service_result,
        ):
            result = nodes.dft_input_preview_node({
                "task_id": "c10-test",
                "dft_approved_slabs": [{"slab_id": "S1"}],
            })

        self.assertEqual(
            result["status"],
            "dft_input_preview_completed",
        )
        self.assertEqual(
            result["dft_input_preview"]["bundle_count"],
            1,
        )

    def test_preview_empty_input_is_skipped(self):
        result = nodes.dft_input_preview_node({
            "task_id": "c10-test",
            "dft_approved_slabs": [],
        })

        self.assertEqual(
            result["status"],
            "dft_input_preview_skipped",
        )

    def test_review_empty_bundle_is_skipped(self):
        result = nodes.dft_input_review_node({
            "dft_input_preview": {
                "bundles": [],
            },
        })

        self.assertEqual(
            result["status"],
            "dft_input_review_skipped",
        )

    def test_finalize_exposes_dft_jobs(self):
        service_result = {
            "schema_version": "c10.0",
            "stage": "c10_finalize",
            "status": "dft_input_preparation_completed",
            "prepared_job_count": 1,
            "failure_count": 0,
            "jobs": [{
                "job_id": "S1",
                "file_count": 5,
            }],
            "failures": [],
        }

        with patch.object(
            nodes.services.vasp_input_bundle_service,
            "finalize",
            return_value=service_result,
        ):
            result = nodes.dft_input_finalize_node({
                "dft_input_preview": {"bundles": []},
                "dft_input_review": {"approve": ["S1"]},
            })

        self.assertEqual(
            result["status"],
            "dft_input_preparation_completed",
        )
        self.assertEqual(result["dft_jobs"][0]["file_count"], 5)

    def test_finalize_exception_is_recorded(self):
        with patch.object(
            nodes.services.vasp_input_bundle_service,
            "finalize",
            side_effect=RuntimeError("test failure"),
        ):
            result = nodes.dft_input_finalize_node({
                "dft_input_preview": {},
                "dft_input_review": {},
                "errors": [],
            })

        self.assertEqual(
            result["status"],
            "dft_input_preparation_failed",
        )
        self.assertEqual(result["dft_jobs"], [])
        self.assertTrue(result["errors"])

    def test_revision_apply_exposes_revised_preview(self):
        service_result = {
            "preview": {"bundles": [{"bundle_id": "S1"}]},
            "validation": {"status": "dft_revision_accepted"},
            "history": [{"bundle_id": "S1"}],
            "revision_count": 1,
        }
        with patch.object(
            nodes.services.dft_input_revision_service,
            "apply",
            return_value=service_result,
        ):
            result = nodes.dft_revision_apply_node({
                "dft_input_preview": {"bundles": []},
                "dft_revision_plan": {"plans": [{}]},
            })

        self.assertEqual(result["status"], "dft_revision_accepted")
        self.assertEqual(result["dft_revision_count"], 1)


if __name__ == "__main__":
    unittest.main()
