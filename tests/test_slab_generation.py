import json
import tempfile
import unittest
from pathlib import Path

from app.domain.slab_generation import (
    SlabGenerationService,
)
from tools.structure_builder import StructureBuilder


class SlabGenerationServiceTest(unittest.TestCase):
    @staticmethod
    def approved_structure(
        directory: str,
    ) -> dict:
        bulk_result = StructureBuilder(
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
        )

        if not bulk_result.get("success"):
            raise RuntimeError(
                "Failed to create the C8 test bulk structure"
            )

        bulk = bulk_result["results"][0]

        return {
            "structure_id": "C8-TEST",
            "candidate_id": "C1",
            "stability_decision": "passed",
            "eligible_for_slab": True,
            "cif_path": bulk["cif_path"],
            "poscar_path": bulk["poscar_path"],
        }

    def test_empty_input_is_skipped(self):
        result = SlabGenerationService().generate([])

        self.assertEqual(
            result["status"],
            "slab_generation_skipped",
        )

    def test_approved_structure_creates_slab(self):
        with tempfile.TemporaryDirectory() as directory:
            service = SlabGenerationService(directory)

            result = service.generate([
                self.approved_structure(directory)
            ])

            self.assertEqual(
                result["status"],
                "slab_generation_completed",
            )
            self.assertEqual(result["slab_count"], 1)

            slab = result["slabs"][0]

            self.assertEqual(slab["atom_count"], 48)
            self.assertEqual(
                slab["vacuum_angstrom"],
                18.0,
            )
            self.assertTrue(
                Path(slab["cif_path"]).is_file()
            )
            self.assertTrue(
                Path(slab["poscar_path"]).is_file()
            )
            self.assertGreater(
                slab["fixed_atom_count"],
                0,
            )
            self.assertGreater(
                slab["movable_atom_count"],
                0,
            )

    def test_unapproved_structure_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            structure = self.approved_structure(directory)
            structure["eligible_for_slab"] = False

            result = SlabGenerationService(
                Path(directory) / "slabs"
            ).generate([structure])

        self.assertEqual(
            result["status"],
            "slab_generation_failed",
        )
        self.assertEqual(result["failure_count"], 1)

    def test_result_is_json_serializable(self):
        result = SlabGenerationService().generate([])
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
