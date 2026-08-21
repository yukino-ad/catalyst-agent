import unittest
from unittest.mock import patch

from app.graph import nodes


class GraphFormationEnergyTest(unittest.TestCase):
    def test_skips_without_bulk_structures(self):
        result = nodes.formation_energy_node({
            "bulk_structures": [],
        })

        self.assertEqual(
            result["status"],
            "formation_energy_skipped",
        )

    def test_exposes_prediction_and_dft_queue(self):
        service_result = {
            "schema_version": "c6.0",
            "stage": "c6",
            "status": "formation_energy_partial",
            "structure_count": 2,
            "cgcnn_predicted_count": 1,
            "waiting_for_dft_count": 1,
            "failed_count": 0,
            "structures": [
                {
                    "structure_id": "S1",
                    "formation_energy": 0.03,
                    "formation_energy_status": "predicted",
                },
                {
                    "structure_id": "S2",
                    "formation_energy": None,
                    "formation_energy_status": "waiting_for_dft",
                },
            ],
            "dft_queue": [{
                "structure_id": "S2",
                "status": "waiting_for_supercomputer",
            }],
            "errors": [],
        }

        with patch.object(
            nodes.services.formation_energy_evaluator,
            "evaluate",
            return_value=service_result,
        ):
            result = nodes.formation_energy_node({
                "bulk_structures": [
                    {"structure_id": "S1"},
                    {"structure_id": "S2"},
                ],
                "warnings": [],
            })

        self.assertEqual(
            len(result["formation_energy_structures"]),
            2,
        )
        self.assertEqual(
            len(result["dft_formation_energy_queue"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()