from __future__ import annotations

import tempfile
from pathlib import Path

from ase.build import fcc111
from ase.constraints import FixAtoms
from ase.io import write

from app.domain.adsorbate_structure_builder import (
    AdsorbateStructureBuilder,
)


class AdsorptionQualityFixture:
    """Create a realistic C12.3 record with VASP constraints."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.contcar = self.root / "CONTCAR"

        atoms = fcc111(
            "Cu",
            size=(4, 4, 3),
            vacuum=12.0,
            orthogonal=True,
        )
        atoms.set_constraint(
            FixAtoms(indices=range(32))
        )
        write(
            str(self.contcar),
            atoms,
            format="vasp",
            direct=True,
            sort=False,
            vasp5=True,
        )

        top_index = int(
            atoms.positions[:, 2].argmax()
        )
        top_position = atoms.positions[top_index]
        site = {
            "site_id": "S1-ontop-001",
            "slab_id": "S1",
            "candidate_id": "C1",
            "clean_slab_slurm_job_id": "123456",
            "site_type": "ontop",
            "cartesian_coordinate_angstrom": [
                float(value) for value in top_position
            ],
            "chemistry_signature": "ontop:Cu|shell:Cu",
            "source_structure_path": str(self.contcar),
            "structure_source": "relaxed_clean_slab_contcar",
            "planned_adsorbates": ["CO"],
            "adsorbate_instance_limit": 1,
            "coadsorption_allowed": False,
        }
        builder = AdsorbateStructureBuilder(
            output_root=self.root / "output"
        )
        result = builder.build(
            "C12-QUALITY",
            [site],
            {
                "formal_adsorbates": ["CO"],
                "ready_for_site_generation": True,
            },
        )
        self.record = result["structures"][0]

    def tearDown(self) -> None:
        self.temporary.cleanup()
