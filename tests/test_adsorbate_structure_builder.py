import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from ase.build import fcc111
from ase.io import read, write

from app.domain.adsorbate_structure_builder import (
    AdsorbateStructureBuilder,
)


class AdsorbateStructureBuilderTest(
    unittest.TestCase
):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.contcar = self.root / "CONTCAR"

        atoms = fcc111(
            "Cu",
            size=(4, 4, 3),
            vacuum=9.0,
            orthogonal=True,
        )

        write(
            str(self.contcar),
            atoms,
            format="vasp",
            direct=True,
            sort=False,
        )

        self.config = (
            Path("configs/adsorbates/"
                 "adsorbates_v1.json")
        )

        self.builder = AdsorbateStructureBuilder(
            config_path=self.config,
            output_root=self.root / "output",
        )

        self.site = {
            "site_id": "S1-ontop-001",
            "slab_id": "S1",
            "candidate_id": "C1",
            "clean_slab_slurm_job_id": "123456",
            "site_type": "ontop",
            "cartesian_coordinate_angstrom": [
                1.0,
                1.0,
                float(
                    atoms.positions[:, 2].max()
                ),
            ],
            "chemistry_signature": (
                "ontop:Cu|shell:Cu"
            ),
            "source_structure_path": str(
                self.contcar
            ),
            "structure_source": (
                "relaxed_clean_slab_contcar"
            ),
            "planned_adsorbates": [
                "H",
                "CO",
                "COOH",
            ],
            "adsorbate_instance_limit": 1,
            "coadsorption_allowed": False,
        }

        self.plan = {
            "formal_adsorbates": [
                "H",
                "CO",
                "COOH",
            ],
            "ready_for_site_generation": True,
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_generates_one_structure_per_adsorbate(self):
        result = self.builder.build(
            "C12-TEST",
            [self.site],
            self.plan,
        )

        self.assertEqual(
            result["generated_structure_count"],
            3,
        )

        self.assertTrue(
            result[
                "single_adsorbate_per_structure"
            ]
        )

        self.assertFalse(
            result["coadsorption_allowed"]
        )

    def test_atom_counts_are_correct(self):
        result = self.builder.build(
            "C12-COUNT",
            [self.site],
            self.plan,
        )

        by_name = {
            item["adsorbate"]: item
            for item in result["structures"]
        }

        self.assertEqual(
            by_name["H"]["total_atom_count"],
            49,
        )
        self.assertEqual(
            by_name["CO"]["total_atom_count"],
            50,
        )
        self.assertEqual(
            by_name["COOH"]["total_atom_count"],
            52,
        )

    def test_clean_slab_coordinates_are_preserved(self):
        clean = read(
            str(self.contcar),
            format="vasp",
        )

        result = self.builder.build(
            "C12-PRESERVE",
            [self.site],
            {
                "formal_adsorbates": ["CO"],
                "ready_for_site_generation": True,
            },
        )

        generated = read(
            result["structures"][0][
                "poscar_path"
            ],
            format="vasp",
        )

        self.assertTrue(
            np.allclose(
                clean.positions,
                generated.positions[:len(clean)],
                atol=1e-10,
            )
        )

    def test_every_structure_has_one_instance(self):
        result = self.builder.build(
            "C12-SINGLE",
            [self.site],
            self.plan,
        )

        for structure in result["structures"]:
            self.assertEqual(
                structure[
                    "adsorbate_instance_count"
                ],
                1,
            )
            self.assertFalse(
                structure["coadsorption"]
            )

    def test_original_poscar_source_is_rejected(self):
        site = dict(self.site)
        site["structure_source"] = (
            "original_slab"
        )

        result = self.builder.build(
            "C12-REJECT",
            [site],
            self.plan,
        )

        self.assertEqual(
            result["generated_structure_count"],
            0,
        )

    def test_result_is_json_serializable(self):
        result = self.builder.build(
            "C12-JSON",
            [self.site],
            self.plan,
        )

        json.dumps(
            result,
            ensure_ascii=False,
        )


if __name__ == "__main__":
    unittest.main()