import json
import unittest
from unittest.mock import patch

from app.domain.adsorption_energy import (
    AdsorptionEnergyCalculator,
)
from app.domain.adsorption_energy_review import (
    AdsorptionEnergyReviewGate,
)
from app.graph import nodes
from app.graph.adsorption_energy_workflow import (
    build_adsorption_energy_graph,
)


def adsorption_result(
    structure_id: str = "A-CO-001",
    energy: float = -500.2,
) -> dict:
    return {
        "job_source": "c12_5_adsorption",
        "job_id": structure_id,
        "slurm_job_id": "123456",
        "vasp_decision": "completed_converged",
        "result_parsing_status": "parsed",
        "parsed_vasp_result": {
            "final_toten_ev": energy,
        },
        "scientific_identity": {
            "adsorption_structure_id": structure_id,
            "candidate_id": "C1",
            "source_clean_slab_id": "S1",
            "site_id": "site-1",
            "site_type": "ontop",
            "adsorbate": "CO",
        },
    }


class AdsorptionEnergyCalculatorTest(unittest.TestCase):
    def setUp(self):
        self.calculator = AdsorptionEnergyCalculator()

    def test_three_energy_subtraction_is_reported(self):
        result = self.calculator.calculate(
            adsorption_results=[adsorption_result()],
            clean_slab_energies={"A-CO-001": -490.0},
            reference_energies={"CO": -9.5},
        )

        self.assertEqual(
            result["status"],
            "adsorption_energy_calculated",
        )
        calculation = result["calculations"][0]
        self.assertAlmostEqual(
            calculation["adsorption_energy_ev"],
            -0.7,
        )
        self.assertNotIn("evaluation_category", calculation)
        self.assertNotIn("adsorption_strength", calculation)
        self.assertNotIn("activity_hint", calculation)
        self.assertEqual(
            calculation["calculation"]["operation"],
            "adsorbed - clean - reference",
        )
        self.assertFalse(
            calculation["automatic_strength_evaluation_performed"]
        )
        self.assertTrue(
            calculation["requires_human_confirmation"]
        )

    def test_structure_specific_reference_has_priority(self):
        result = self.calculator.calculate(
            adsorption_results=[adsorption_result()],
            clean_slab_energies={"A-CO-001": -490.0},
            reference_energies={
                "CO": -9.5,
                "A-CO-001": -9.0,
            },
        )

        calculation = result["calculations"][0]
        self.assertAlmostEqual(
            calculation["adsorption_energy_ev"],
            -1.2,
        )

    def test_versioned_reference_record_is_preserved(self):
        reference = {
            "reference_scheme": "gas_phase",
            "reference_expression": "E_CO",
            "components": {"CO": -9.5},
            "resolved_reference_energy_ev": -9.5,
            "energy_unit": "eV",
            "data_version": "co-reference-v1",
        }
        result = self.calculator.calculate(
            adsorption_results=[adsorption_result()],
            clean_slab_energies={
                "S1": {
                    "clean_slab_energy_ev": -490.0,
                    "data_version": "clean-v1",
                }
            },
            reference_energies={"CO": reference},
        )
        calculation = result["calculations"][0]
        self.assertEqual(
            calculation["reference_energy_provenance"]["data_version"],
            "co-reference-v1",
        )

    def test_missing_clean_slab_energy_is_recorded(self):
        result = self.calculator.calculate(
            adsorption_results=[adsorption_result()],
            clean_slab_energies={},
            reference_energies={"CO": -9.5},
        )

        self.assertEqual(
            result["status"],
            "adsorption_energy_failed",
        )
        self.assertEqual(result["calculated_count"], 0)
        self.assertEqual(result["failed_count"], 1)
        self.assertIn(
            "Clean slab energy is missing",
            result["errors"][0]["message"],
        )

    def test_result_is_json_serializable(self):
        result = self.calculator.calculate(
            adsorption_results=[adsorption_result()],
            clean_slab_energies={"A-CO-001": -490.0},
            reference_energies={"CO": -9.5},
        )
        json.dumps(result, ensure_ascii=False)


class AdsorptionEnergyReviewGateTest(unittest.TestCase):
    def setUp(self):
        calculation = AdsorptionEnergyCalculator().calculate(
            adsorption_results=[adsorption_result()],
            clean_slab_energies={"A-CO-001": -490.0},
            reference_energies={"CO": -9.5},
        )
        self.calculations = calculation["calculations"]
        self.gate = AdsorptionEnergyReviewGate()

    def test_approved_result_is_exposed(self):
        result = self.gate.review(
            self.calculations,
            {
                "approve": ["AE-A-CO-001"],
                "reject": [],
                "defer": [],
                "note": "manual calculation checked",
            },
        )

        self.assertEqual(result["approved_count"], 1)
        self.assertEqual(
            result["approved"][0][
                "adsorption_energy_review_status"
            ],
            "approved",
        )

    def test_unclassified_result_is_deferred(self):
        result = self.gate.review(
            self.calculations,
            {"approve": [], "reject": [], "defer": []},
        )
        self.assertEqual(result["deferred_count"], 1)

    def test_conflicting_decision_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "multiple decisions",
        ):
            self.gate.review(
                self.calculations,
                {
                    "approve": ["AE-A-CO-001"],
                    "reject": ["AE-A-CO-001"],
                    "defer": [],
                },
            )


class GraphAdsorptionEnergyTest(unittest.TestCase):
    def test_graph_contains_calculation_and_review_nodes(self):
        graph = build_adsorption_energy_graph().get_graph()
        names = set(graph.nodes)
        self.assertIn("adsorption_energy_calculation", names)
        self.assertIn("adsorption_energy_review", names)

    def test_nodes_calculate_then_approve(self):
        calculated = nodes.adsorption_energy_calculation_node({
            "adsorption_parsed_results": [adsorption_result()],
            "clean_slab_energies": {"A-CO-001": -490.0},
            "reference_energies": {"CO": -9.5},
            "errors": [],
        })

        with patch(
            "app.graph.nodes.interrupt",
            return_value={
                "approve": ["AE-A-CO-001"],
                "reject": [],
                "defer": [],
                "note": "checked",
            },
        ):
            reviewed = nodes.adsorption_energy_review_node({
                "adsorption_energy_drafts": calculated[
                    "adsorption_energy_drafts"
                ],
                "errors": [],
            })

        self.assertEqual(
            reviewed["status"],
            "adsorption_energy_review_completed",
        )
        self.assertEqual(
            len(reviewed["approved_adsorption_energies"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
