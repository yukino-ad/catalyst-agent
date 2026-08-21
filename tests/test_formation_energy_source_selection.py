import unittest
from unittest.mock import patch

from app.graph.nodes import stability_screening_node
from app.graph.routes import route_after_formation_energy_source_review
from app.api.review_contract import validate_review_decision


class FormationEnergySourceSelectionTest(unittest.TestCase):
    def test_c7_uses_selected_structures_only(self):
        selected = [{"structure_id": "selected", "formation_energy": -0.05}]
        state = {
            "formation_energy_structures": [{"structure_id": "production", "formation_energy": 0.1}],
            "selected_formation_energy_structures": selected,
            "warnings": [],
        }
        with patch("app.graph.nodes.services.stability_screening_evaluator.evaluate") as evaluate:
            evaluate.return_value = {
                "status": "stability_screening_completed",
                "structures": [],
                "slab_eligible_structures": [],
            }
            stability_screening_node(state)
        evaluate.assert_called_once_with(selected)

    def test_defer_stops_before_c7(self):
        self.assertEqual(
            route_after_formation_energy_source_review({
                "selected_formation_energy_source": "defer",
                "selected_formation_energy_structures": [],
            }),
            "end",
        )

    def test_temporary_source_enters_c7(self):
        self.assertEqual(
            route_after_formation_energy_source_review({
                "selected_formation_energy_source": "temporary_trained",
                "selected_formation_energy_structures": [{"structure_id": "S1"}],
            }),
            "stability",
        )

    def test_unfinished_temporary_model_is_rejected(self):
        review = {
            "options": [
                {"mode": "pretrained"},
                {"mode": "temporary_trained"},
                {"mode": "defer"},
            ],
            "temporary_model_ready": False,
        }
        with self.assertRaisesRegex(ValueError, "has not completed"):
            validate_review_decision(
                review,
                "formation_energy_source_review_required",
                {"mode": "temporary_trained"},
            )


if __name__ == "__main__":
    unittest.main()
