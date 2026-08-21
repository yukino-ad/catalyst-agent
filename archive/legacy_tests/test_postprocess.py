import unittest
from pathlib import Path

from app.legacy.postprocess_service import PostprocessService


class PostprocessTest(unittest.TestCase):
    def test_passed_bulk_creates_48_atom_111_slab(self):
        root = Path(__file__).resolve().parents[1]
        cif = root / "data" / "structures" / "cif" / "Cu_HEA_FCC_00001_Al3_Co7_Cr7_Cu8_Mn7_3f4f44e5.cif"
        poscar = root / "data" / "structures" / "POSCAR" / "Cu_HEA_FCC_00001_Al3_Co7_Cr7_Cu8_Mn7_3f4f44e5.vasp"
        result = PostprocessService(root).screen_and_cleave([cif], [poscar])
        self.assertTrue(result["screening"][0]["passed"])
        self.assertLessEqual(result["screening"][0]["delta_percent"], 6.6)
        self.assertGreaterEqual(result["screening"][0]["omega"], 1.1)
        self.assertEqual(len(result["slabs"]), 1)
        self.assertEqual(result["slabs"][0]["atom_count"], 48)
        self.assertEqual(result["slabs"][0]["vacuum_angstrom"], 18.0)
        self.assertTrue(Path(result["slabs"][0]["cif_path"]).is_file())
        self.assertTrue(Path(result["slabs"][0]["poscar_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
