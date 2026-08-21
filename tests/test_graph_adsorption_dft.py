import json
import unittest
from unittest.mock import patch

from app.graph import nodes
from app.graph.routes import (
    route_after_adsorption_dft_review,
)


class GraphAdsorptionDFTTest(unittest.TestCase):
    def test_review_route_supports_revision_loop(self):
        self.assertEqual(
            route_after_adsorption_dft_review({
                "adsorption_dft_input_review": {
                    "action": "revise"
                }
            }),
            "revise",
        )
        self.assertEqual(
            route_after_adsorption_dft_review({
                "adsorption_dft_input_review": {
                    "action": "finalize"
                }
            }),
            "finalize",
        )

    def test_preview_uses_c12_4_approved_structures(self):
        domain_result = {
            "status": "adsorption_dft_preview_completed",
            "bundle_count": 1,
            "bundles": [{"bundle_id": "A"}],
        }
        structures = [{"adsorption_structure_id": "A"}]
        with patch.object(
            nodes.services.adsorption_dft_input_bundle_service,
            "preview",
            return_value=domain_result,
        ) as mocked:
            result = nodes.adsorption_dft_preview_node({
                "task_id": "T1",
                "adsorption_dft_approved_structures": structures,
            })
        mocked.assert_called_once_with(
            approved_structures=structures,
            task_id="T1",
        )
        self.assertEqual(result["adsorption_dft_input_preview"], domain_result)

    def test_empty_review_is_skipped(self):
        result = nodes.adsorption_dft_review_node({
            "adsorption_dft_input_preview": {"bundles": []},
        })
        self.assertEqual(result["status"], "adsorption_dft_review_skipped")

    def test_review_interrupt_has_c12_5_identity(self):
        bundles = [{"bundle_id": "A", "preview": {}}]
        with patch(
            "app.graph.nodes.interrupt",
            return_value={"action": "finalize", "approve": ["A"]},
        ) as mocked:
            result = nodes.adsorption_dft_review_node({
                "adsorption_dft_input_preview": {"bundles": bundles},
                "adsorption_dft_revision_count": 0,
            })
        request = mocked.call_args.args[0]
        self.assertEqual(request["type"], "adsorption_dft_input_review_required")
        self.assertTrue(request["poscar_immutable"])
        self.assertFalse(request["submission_performed"])
        self.assertEqual(result["status"], "adsorption_dft_review_completed")

    def test_revision_apply_requires_another_review(self):
        service_result = {
            "preview": {"bundles": [{"bundle_id": "A"}]},
            "validation": {"poscar_unchanged": True},
            "history": [{"bundle_id": "A"}],
            "revision_count": 1,
        }
        with patch.object(
            nodes.services.adsorption_dft_input_revision_service,
            "apply",
            return_value=service_result,
        ):
            result = nodes.adsorption_dft_revision_apply_node({
                "adsorption_dft_input_preview": {"bundles": []},
                "adsorption_dft_revision_plan": {"plans": [{}]},
            })
        self.assertEqual(result["adsorption_dft_input_review"], {})
        self.assertEqual(result["adsorption_dft_revision_count"], 1)

    def test_finalize_exposes_adsorption_jobs(self):
        domain_result = {
            "status": "dft_input_preparation_completed",
            "jobs": [{
                "job_id": "A",
                "job_source": "c12_5_adsorption",
            }],
        }
        with patch.object(
            nodes.services.adsorption_dft_input_bundle_service,
            "finalize",
            return_value=domain_result,
        ):
            result = nodes.adsorption_dft_finalize_node({
                "adsorption_dft_input_preview": {},
                "adsorption_dft_input_review": {},
            })
        self.assertEqual(result["adsorption_dft_jobs"], domain_result["jobs"])

    def test_results_are_json_serializable(self):
        with patch.object(
            nodes.services.adsorption_dft_input_bundle_service,
            "preview",
            return_value={
                "status": "adsorption_dft_preview_skipped",
                "bundles": [],
            },
        ):
            result = nodes.adsorption_dft_preview_node({
                "task_id": "T1",
                "adsorption_dft_approved_structures": [],
            })
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
