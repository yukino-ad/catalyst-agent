import unittest
from unittest.mock import patch

from app.graph import nodes


class GraphSlabQualityTest(unittest.TestCase):
    def test_exposes_quality_passed_slabs(self):
        service_result = {
            "schema_version": "c9.0",
            "stage": "c9_quality",
            "status": "slab_quality_completed_all_passed",
            "input_slab_count": 1,
            "checked_count": 1,
            "passed_count": 1,
            "failed_count": 0,
            "error_count": 0,
            "reports": [{
                "slab_id": "S1",
                "quality_decision": "passed",
                "eligible_for_dft_review": True,
            }],
            "quality_passed_slabs": [{
                "slab_id": "S1",
                "quality_decision": "passed",
                "eligible_for_dft_review": True,
            }],
            "errors": [],
        }

        with patch.object(
            nodes.services.slab_quality_inspector,
            "inspect",
            return_value=service_result,
        ):
            result = nodes.slab_quality_node({
                "generated_slabs": [{
                    "slab_id": "S1",
                }],
                "warnings": [],
            })

        self.assertEqual(
            result["status"],
            "slab_quality_completed_all_passed",
        )
        self.assertEqual(
            result["quality_passed_slabs"][0][
                "slab_id"
            ],
            "S1",
        )

    def test_empty_input_is_skipped(self):
        result = nodes.slab_quality_node({
            "generated_slabs": [],
            "warnings": [],
        })

        self.assertEqual(
            result["status"],
            "slab_quality_skipped",
        )


if __name__ == "__main__":
    unittest.main()