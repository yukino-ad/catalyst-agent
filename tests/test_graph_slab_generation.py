import unittest
from unittest.mock import patch

from app.graph import nodes


class GraphSlabGenerationTest(unittest.TestCase):
    def test_empty_input_is_skipped(self):
        result = nodes.slab_generation_node({
            "slab_eligible_structures": [],
            "warnings": [],
        })

        self.assertEqual(
            result["status"],
            "slab_generation_skipped",
        )
        self.assertEqual(result["generated_slabs"], [])

    def test_exposes_generated_slabs(self):
        service_result = {
            "schema_version": "c8.0",
            "stage": "c8",
            "status": "slab_generation_completed",
            "input_structure_count": 1,
            "slab_count": 1,
            "failure_count": 0,
            "slabs": [{
                "slab_id": "S1-slab111",
                "source_structure_id": "S1",
                "atom_count": 48,
                "vacuum_angstrom": 18.0,
                "cif_path": "slab.cif",
                "poscar_path": "slab.vasp",
            }],
            "failures": [],
        }

        with patch.object(
            nodes.services.slab_generation_service,
            "generate",
            return_value=service_result,
        ):
            result = nodes.slab_generation_node({
                "slab_eligible_structures": [{
                    "structure_id": "S1",
                    "eligible_for_slab": True,
                }],
                "warnings": [],
            })

        self.assertEqual(
            result["status"],
            "slab_generation_completed",
        )
        self.assertEqual(
            result["generated_slabs"][0][
                "atom_count"
            ],
            48,
        )


if __name__ == "__main__":
    unittest.main()