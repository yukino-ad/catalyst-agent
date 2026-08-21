import json
import tempfile
import unittest
from pathlib import Path

from app.domain.structure_modeling import (
    FCCStructureModeler,
)
from tools.structure_builder import StructureBuilder


class FCCStructureModelerTest(unittest.TestCase):
    @staticmethod
    def cu_candidate():
        return {
            "candidate_id": "C-CU",
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

    @staticmethod
    def non_cu_candidate():
        return {
            "candidate_id": "C-NO-CU",
            "rank": 2,
            "elements": [
                "Fe", "Co", "Ni", "Mn", "Mo",
            ],
            "composition": {
                "Fe": 7,
                "Co": 7,
                "Ni": 6,
                "Mn": 6,
                "Mo": 6,
            },
        }

    def test_empty_selection_is_skipped(self):
        result = FCCStructureModeler().model_candidates([])

        self.assertEqual(
            result["status"],
            "structure_modeling_skipped",
        )
        self.assertEqual(result["structure_count"], 0)

    def test_models_cu_and_non_cu_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            modeler = FCCStructureModeler(
                builder=StructureBuilder(directory)
            )

            result = modeler.model_candidates([
                self.cu_candidate(),
                self.non_cu_candidate(),
            ])

            self.assertEqual(
                result["status"],
                "structure_modeling_completed",
            )
            self.assertEqual(result["structure_count"], 2)
            self.assertEqual(
                result["modeled_candidate_count"],
                2,
            )

            for structure in result["structures"]:
                self.assertEqual(
                    structure["atom_count"],
                    32,
                )
                self.assertTrue(
                    Path(
                        structure["cif_path"]
                    ).is_file()
                )
                self.assertTrue(
                    Path(
                        structure["poscar_path"]
                    ).is_file()
                )
                self.assertIsNone(
                    structure["formation_energy"]
                )
                self.assertFalse(
                    structure["eligible_for_slab"]
                )

    def test_rejects_invalid_atom_count(self):
        candidate = self.cu_candidate()
        candidate["composition"]["Cu"] = 7

        with tempfile.TemporaryDirectory() as directory:
            modeler = FCCStructureModeler(
                StructureBuilder(directory)
            )
            result = modeler.model_candidates([candidate])

        self.assertEqual(
            result["status"],
            "structure_modeling_failed",
        )
        self.assertEqual(result["failure_count"], 1)

    def test_result_is_json_serializable(self):
        result = FCCStructureModeler().model_candidates([])
        text = json.dumps(result, ensure_ascii=False)
        self.assertIn("c5.0", text)


if __name__ == "__main__":
    unittest.main()