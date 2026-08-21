import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.domain.formation_energy import (
    FormationEnergyEvaluator,
)


class FormationEnergyEvaluatorTest(unittest.TestCase):
    @staticmethod
    def structure(
        cif_path: str,
        elements: list[str],
        structure_id: str,
    ) -> dict:
        return {
            "structure_id": structure_id,
            "candidate_id": "C1",
            "elements": elements,
            "composition": {
                element: 1
                for element in elements
            },
            "atom_count": 32,
            "cif_path": cif_path,
            "poscar_path": "POSCAR.vasp",
            "eligible_for_slab": False,
        }

    def test_domain_structure_uses_cgcnn(self):
        with tempfile.TemporaryDirectory() as directory:
            cif = Path(directory) / "test.cif"
            cif.write_text("data_test\n", encoding="utf-8")

            cgcnn = Mock()
            cgcnn.predict.return_value = [{
                "cif_id": "agent_candidate_0001",
                "formation_energy_per_atom": 0.031,
                "unit": "eV/atom",
                "model_path": "model_best.pth.tar",
            }]

            evaluator = FormationEnergyEvaluator(cgcnn)
            result = evaluator.evaluate([
                self.structure(
                    str(cif),
                    ["Cu", "Fe", "Co", "Ni", "Mn"],
                    "S1",
                )
            ])

        cgcnn.predict.assert_called_once()

        structure = result["structures"][0]
        self.assertEqual(
            structure["formation_energy_status"],
            "predicted",
        )
        self.assertAlmostEqual(
            structure["formation_energy"],
            0.031,
        )
        self.assertFalse(
            structure["eligible_for_slab"]
        )

    def test_au_structure_is_routed_to_dft(self):
        cgcnn = Mock()
        evaluator = FormationEnergyEvaluator(cgcnn)

        result = evaluator.evaluate([
            self.structure(
                "not_needed_for_dft_route.cif",
                ["Cu", "Au", "Fe", "Co", "Ni"],
                "S-AU",
            )
        ])

        cgcnn.predict.assert_not_called()

        structure = result["structures"][0]
        self.assertEqual(
            structure["formation_energy_status"],
            "waiting_for_dft",
        )
        self.assertEqual(
            structure["cgcnn_unsupported_elements"],
            ["Au"],
        )
        self.assertEqual(len(result["dft_queue"]), 1)

    def test_empty_input_is_skipped(self):
        result = FormationEnergyEvaluator(
            Mock()
        ).evaluate([])

        self.assertEqual(
            result["status"],
            "formation_energy_skipped",
        )

    def test_result_is_json_serializable(self):
        result = FormationEnergyEvaluator(
            Mock()
        ).evaluate([])

        text = json.dumps(result, ensure_ascii=False)
        self.assertIn("c6.0", text)


if __name__ == "__main__":
    unittest.main()