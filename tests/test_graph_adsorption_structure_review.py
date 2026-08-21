import json
import unittest
from unittest.mock import patch

from app.graph.nodes import (
    adsorption_structure_quality_node,
    adsorption_structure_review_node,
)


class GraphAdsorptionStructureReviewTest(unittest.TestCase):
    def test_quality_node_writes_flat_passed_list(self):
        domain_result = {
            "status": "adsorption_quality_completed_all_passed",
            "quality_passed_structures": [{"adsorption_structure_id": "A"}],
        }
        with patch(
            "app.graph.nodes.services."
            "adsorption_structure_quality_inspector.inspect",
            return_value=domain_result,
        ):
            result = adsorption_structure_quality_node({
                "adsorption_structures": [{}],
                "errors": [],
            })
        self.assertEqual(
            result["quality_passed_adsorption_structures"],
            domain_result["quality_passed_structures"],
        )

    def test_quality_node_records_error(self):
        with patch(
            "app.graph.nodes.services."
            "adsorption_structure_quality_inspector.inspect",
            side_effect=ValueError("invalid geometry"),
        ):
            result = adsorption_structure_quality_node({
                "adsorption_structures": [{}],
                "errors": [],
            })
        self.assertEqual(result["status"], "adsorption_quality_failed")
        self.assertEqual(result["quality_passed_adsorption_structures"], [])
        self.assertEqual(len(result["errors"]), 1)

    def test_empty_review_is_skipped(self):
        result = adsorption_structure_review_node({
            "quality_passed_adsorption_structures": [],
        })
        self.assertEqual(
            result["status"],
            "adsorption_structure_review_skipped",
        )

    def test_review_interrupt_is_bound_to_structures(self):
        values = [{
            "adsorption_structure_id": "A",
            "slab_id": "S1",
            "adsorbate": "CO",
            "site_id": "site-1",
            "site_type": "ontop",
            "chemistry_signature": "ontop:Cu",
            "eligible_for_adsorption_review": True,
            "adsorbate_instance_count": 1,
            "coadsorption": False,
        }]
        domain_result = {
            "status": "adsorption_structure_review_completed",
            "approved": values,
        }
        with patch(
            "app.graph.nodes.interrupt",
            return_value={"approve": ["A"]},
        ) as mocked_interrupt, patch(
            "app.graph.nodes.services."
            "adsorption_structure_review_gate.review",
            return_value=domain_result,
        ) as mocked_review:
            result = adsorption_structure_review_node({
                "quality_passed_adsorption_structures": values,
                "errors": [],
            })
        payload = mocked_interrupt.call_args.args[0]
        self.assertEqual(payload["type"], "adsorption_structure_review_required")
        self.assertEqual(payload["structures"][0]["adsorption_structure_id"], "A")
        mocked_review.assert_called_once_with(values, {"approve": ["A"]})
        self.assertEqual(result["adsorption_dft_approved_structures"], values)

    def test_review_node_records_error(self):
        values = [{"adsorption_structure_id": "A"}]
        with patch(
            "app.graph.nodes.interrupt",
            return_value={"approve": ["A"]},
        ), patch(
            "app.graph.nodes.services."
            "adsorption_structure_review_gate.review",
            side_effect=ValueError("invalid decision"),
        ):
            result = adsorption_structure_review_node({
                "quality_passed_adsorption_structures": values,
                "errors": [],
            })
        self.assertEqual(
            result["status"],
            "adsorption_structure_review_failed",
        )
        self.assertEqual(result["adsorption_dft_approved_structures"], [])
        self.assertEqual(len(result["errors"]), 1)

    def test_results_are_json_serializable(self):
        quality = adsorption_structure_quality_node({
            "adsorption_structures": [],
            "errors": [],
        })
        review = adsorption_structure_review_node({
            "quality_passed_adsorption_structures": [],
        })
        json.dumps({"quality": quality, "review": review}, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
