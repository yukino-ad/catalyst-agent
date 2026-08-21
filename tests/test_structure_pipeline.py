import tempfile
import unittest
from pathlib import Path

from tools.candidate_generator import CandidateGenerator
from tools.structure_builder import StructureBuilder


class StructurePipelineTest(unittest.TestCase):
    def test_noble_metal_candidate_uses_requested_lattice_and_composition(self):
        elements = ["Cu", "Au", "Ag", "Pt", "Pd"]
        evidence = [["Au", "Ag", "Pt", "Pd", "Cu"]]
        candidate = CandidateGenerator(prefer_elements=elements).generate(
            top_k=1, evidence_element_sets=evidence
        )[0]
        self.assertEqual(candidate["composition"], {"Cu": 8, "Au": 6, "Ag": 6, "Pt": 6, "Pd": 6})
        self.assertEqual(candidate["literature_score"], 20)
        with tempfile.TemporaryDirectory() as directory:
            result = StructureBuilder(directory).generate(
                selected_elements=elements, composition=candidate["composition"], seed=7
            )
        structure = result["results"][0]
        expected_a0 = (8 * 3.615 + 6 * 4.095 + 6 * 4.095 + 6 * 3.885 + 6 * 3.885) / 32
        self.assertEqual(structure["counts"], candidate["composition"])
        self.assertAlmostEqual(structure["lattice_constant_a0"], expected_a0, places=6)

    def test_all_candidates_are_model_compatible(self):
        candidates = CandidateGenerator().generate(top_k=20)
        supported = StructureBuilder.SUPPORTED_ELEMENTS
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertEqual(len(candidate["elements"]), 5)
            self.assertIn("Cu", candidate["elements"])
            self.assertLessEqual(len(set(candidate["elements"]) & StructureBuilder.P_ELEMENTS), 1)
            self.assertLessEqual(set(candidate["elements"]), supported)
            self.assertEqual(sum(candidate["composition"].values()), 32)

    def test_builder_writes_cif_and_poscar(self):
        candidate = CandidateGenerator().generate(top_k=1)[0]
        with tempfile.TemporaryDirectory() as directory:
            result = StructureBuilder(directory).generate(
                selected_elements=candidate["elements"],
                composition=candidate["composition"],
                seed=42,
            )
            self.assertTrue(result["success"])
            self.assertTrue(Path(result["results"][0]["cif_path"]).is_file())
            self.assertTrue(Path(result["results"][0]["poscar_path"]).is_file())

if __name__ == "__main__":
    unittest.main()
