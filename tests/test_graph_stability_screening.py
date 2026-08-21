import unittest
from unittest.mock import patch

from app.graph import nodes


class GraphStabilityScreeningTest(unittest.TestCase):
    def test_exposes_slab_eligible_structures(self):
        service_result = {
            "schema_version": "c7.0",
            "stage": "c7",
            "status": (
                "stability_screening_completed_all_passed"
            ),
            "structure_count": 1,
            "passed_count": 1,
            "failed_count": 0,
            "pending_count": 0,
            "evaluation_error_count": 0,
            "structures": [{
                "structure_id": "S1",
                "stability_decision": "passed",
                "eligible_for_slab": True,
            }],
            "slab_eligible_structures": [{
                "structure_id": "S1",
                "eligible_for_slab": True,
            }],
            "errors": [],
        }

        with patch.object(
            nodes.services.stability_screening_evaluator,
            "evaluate",
            return_value=service_result,
        ):
            result = nodes.stability_screening_node({
                "formation_energy_structures": [{
                    "structure_id": "S1",
                }],
                "warnings": [],
            })

        self.assertEqual(
            len(result["slab_eligible_structures"]),
            1,
        )

    def test_empty_input_is_skipped(self):
        result = nodes.stability_screening_node({
            "formation_energy_structures": [],
            "warnings": [],
        })

        self.assertEqual(
            result["status"],
            "stability_screening_skipped",
        )


if __name__ == "__main__":
    unittest.main()