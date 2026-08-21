import json
import tempfile
import unittest
from pathlib import Path

from app.domain.slab_generation import (
    SlabGenerationService,
)
from app.domain.slab_quality import (
    SlabQualityInspector,
)
from tools.structure_builder import StructureBuilder


class SlabQualityInspectorTest(unittest.TestCase):
    @staticmethod
    def create_slab(directory: str) -> dict:
        bulk = StructureBuilder(
            Path(directory) / "bulk"
        ).generate(
            selected_elements=[
                "Cu", "Al", "Co", "Cr", "Mn",
            ],
            composition={
                "Cu": 8,
                "Al": 3,
                "Co": 7,
                "Cr": 7,
                "Mn": 7,
            },
            generation_mode="composition_driven",
            seed=42,
        )["results"][0]

        c8_input = {
            "structure_id": "C9-TEST",
            "candidate_id": "C1",
            "stability_decision": "passed",
            "eligible_for_slab": True,
            "cif_path": bulk["cif_path"],
            "poscar_path": bulk["poscar_path"],
        }

        return SlabGenerationService(
            Path(directory) / "slabs"
        ).generate([c8_input])["slabs"][0]

    def test_valid_c8_slab_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            slab = self.create_slab(directory)
            result = SlabQualityInspector(
                Path(directory) / "quality"
            ).inspect([slab])

        self.assertEqual(
            result["status"],
            "slab_quality_completed_all_passed",
        )
        self.assertEqual(result["passed_count"], 1)

        report = result["reports"][0]
        self.assertEqual(report["atom_count"], 48)
        self.assertEqual(report["fixed_atom_count"], 32)
        self.assertEqual(report["movable_atom_count"], 16)
        self.assertTrue(
            report["eligible_for_dft_review"]
        )

    def test_empty_input_is_skipped(self):
        result = SlabQualityInspector().inspect([])

        self.assertEqual(
            result["status"],
            "slab_quality_skipped",
        )
        self.assertEqual(
            result["quality_passed_slabs"],
            [],
        )

    def test_missing_file_is_reported(self):
        result = SlabQualityInspector().inspect([{
            "slab_id": "missing",
            "poscar_path": "missing.vasp",
        }])

        self.assertEqual(
            result["status"],
            "slab_quality_failed",
        )
        self.assertEqual(result["error_count"], 1)

    def test_result_is_json_serializable(self):
        result = SlabQualityInspector().inspect([])
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()