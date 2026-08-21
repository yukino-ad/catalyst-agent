import unittest
from unittest.mock import patch

from app.graph import nodes


class GraphStructureModelingTest(unittest.TestCase):
    @staticmethod
    def candidate():
        return {
            "candidate_id": "C1",
            "rank": 1,
            "elements": [
                "Cu", "Fe", "Co", "Ni", "Mn",
            ],
            "composition": {
                "Cu": 8,
                "Fe": 6,
                "Co": 6,
                "Ni": 6,
                "Mn": 6,
            },
        }

    def test_skips_without_selected_candidates(self):
        result = nodes.structure_modeling_node({
            "candidate_review": {
                "ready_for_structure_modeling": False,
            },
            "selected_candidates": [],
        })

        self.assertEqual(
            result["status"],
            "structure_modeling_skipped",
        )
        self.assertEqual(result["bulk_structures"], [])

    def test_models_selected_candidates(self):
        modeling_result = {
            "schema_version": "c5.0",
            "stage": "c5",
            "status": "structure_modeling_completed",
            "selected_candidate_count": 1,
            "modeled_candidate_count": 1,
            "structure_count": 1,
            "structures": [{
                "structure_id": "C1-fcc-01",
                "candidate_id": "C1",
                "atom_count": 32,
                "cif_path": "test.cif",
                "poscar_path": "POSCAR.vasp",
            }],
            "failure_count": 0,
            "failures": [],
        }

        with patch.object(
            nodes.services.structure_modeler,
            "model_candidates",
            return_value=modeling_result,
        ) as mocked:
            result = nodes.structure_modeling_node({
                "candidate_review": {
                    "ready_for_structure_modeling": True,
                },
                "selected_candidates": [
                    self.candidate()
                ],
                "warnings": [],
                "errors": [],
            })

        mocked.assert_called_once()

        self.assertEqual(
            result["status"],
            "structure_modeling_completed",
        )
        self.assertEqual(
            result["bulk_structures"][0][
                "structure_id"
            ],
            "C1-fcc-01",
        )


if __name__ == "__main__":
    unittest.main()
