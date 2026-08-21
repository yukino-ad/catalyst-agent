import json
import tempfile
import unittest
from pathlib import Path

from ase.build import fcc111
from ase.io import read, write

from app.domain.adsorption_site_generation import (
    AdsorptionSiteGenerationService,
)


class AdsorptionSiteGenerationServiceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.contcar = self.root / "CONTCAR"
        atoms = fcc111("Cu", size=(4, 4, 3), vacuum=9.0, orthogonal=True)
        elements = ["Cu", "Ni", "Fe", "Co", "Au"]
        atoms.set_chemical_symbols([
            elements[index % len(elements)] for index in range(len(atoms))
        ])
        write(str(self.contcar), atoms, format="vasp", direct=True, sort=False)
        parsed_atoms = read(str(self.contcar), format="vasp")
        composition = {}
        for symbol in parsed_atoms.get_chemical_symbols():
            composition[symbol] = composition.get(symbol, 0) + 1
        self.parsed_structure = {
            "elements": list(composition),
            "counts": list(composition.values()),
            "atom_count": len(parsed_atoms),
            "path": str(self.contcar.resolve()),
        }
        self.plan = {
            "formal_adsorbates": ["COOH", "CO", "H"],
            "ready_for_site_generation": True,
        }
        self.slab = {
            "slab_id": "S1-slab111",
            "candidate_id": "C1",
            "clean_slab_slurm_job_id": "123456",
            "clean_slab_dft_status": "completed_converged",
            "clean_slab_result_parsing_status": "parsed",
            "relaxed_contcar_path": str(self.contcar),
            "approved_for_adsorption": True,
            "structure_source": "relaxed_clean_slab_contcar",
            "parsed_final_structure": self.parsed_structure,
            "submitted_scientific_identity": {
                "slab_id": "S1-slab111",
                "candidate_id": "C1",
            },
        }
        self.service = AdsorptionSiteGenerationService()

    def tearDown(self):
        self.temporary.cleanup()

    def test_converged_contcar_generates_bounded_sites(self):
        result = self.service.generate([self.slab], self.plan)
        self.assertEqual(result["status"], "adsorption_site_generation_completed")
        self.assertGreater(result["site_count"], 0)
        self.assertLessEqual(result["site_count"], 15)
        self.assertTrue(result["local_chemistry_preserved"])
        self.assertEqual(
            result["slabs"][0]["clean_slab_slurm_job_id"], "123456"
        )
        self.assertTrue({site["site_type"] for site in result["sites"]}.issubset(
            {"ontop", "bridge", "hollow"}
        ))

    def test_single_adsorbate_contract_is_propagated(self):
        result = self.service.generate([self.slab], self.plan)
        self.assertEqual(result["adsorbate_instance_limit"], 1)
        self.assertFalse(result["coadsorption_allowed"])
        self.assertFalse(result["adsorbate_placed"])
        for site in result["sites"]:
            self.assertEqual(site["adsorbate_instance_limit"], 1)
            self.assertFalse(site["coadsorption_allowed"])

    def test_contcar_is_not_modified(self):
        before = self.contcar.read_bytes()
        result = self.service.generate([self.slab], self.plan)
        self.assertEqual(before, self.contcar.read_bytes())
        self.assertFalse(result["structure_modified"])

    def test_original_poscar_fallback_is_rejected(self):
        poscar = self.root / "POSCAR"
        poscar.write_bytes(self.contcar.read_bytes())
        slab = {
            **self.slab,
            "relaxed_contcar_path": str(poscar),
            "structure_source": "original_slab",
        }
        result = self.service.generate([slab], self.plan)
        self.assertEqual(result["status"], "adsorption_site_generation_failed")
        self.assertFalse(result["original_slab_fallback_allowed"])

    def test_unconverged_or_unparsed_result_is_rejected(self):
        for field, value in (
            ("clean_slab_dft_status", "incomplete"),
            ("clean_slab_result_parsing_status", "pending"),
        ):
            with self.subTest(field=field):
                result = self.service.generate(
                    [{**self.slab, field: value}], self.plan
                )
                self.assertEqual(
                    result["status"], "adsorption_site_generation_failed"
                )

    def test_unapproved_result_is_rejected(self):
        result = self.service.generate(
            [{**self.slab, "approved_for_adsorption": False}], self.plan
        )
        self.assertEqual(result["status"], "adsorption_site_generation_failed")

    def test_submitted_identity_mismatch_is_rejected(self):
        slab = {
            **self.slab,
            "submitted_scientific_identity": {
                "slab_id": "another-slab",
                "candidate_id": "C1",
            },
        }
        result = self.service.generate([slab], self.plan)
        self.assertEqual(result["status"], "adsorption_site_generation_failed")

    def test_parsed_composition_mismatch_is_rejected(self):
        parsed = {**self.parsed_structure, "atom_count": 999}
        result = self.service.generate(
            [{**self.slab, "parsed_final_structure": parsed}], self.plan
        )
        self.assertEqual(result["status"], "adsorption_site_generation_failed")

    def test_unready_plan_blocks_generation(self):
        result = self.service.generate(
            [self.slab], {**self.plan, "ready_for_site_generation": False}
        )
        self.assertEqual(result["status"], "adsorption_site_generation_blocked")
        self.assertEqual(result["site_count"], 0)

    def test_result_is_json_serializable(self):
        json.dumps(self.service.generate([self.slab], self.plan), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
