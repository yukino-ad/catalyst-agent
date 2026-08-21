import json
import unittest

from ase.constraints import FixAtoms
from ase.io import read, write

from app.domain.adsorption_structure_quality import (
    AdsorptionStructureQualityInspector,
)
from tests.adsorption_quality_test_utils import (
    AdsorptionQualityFixture,
)


class AdsorptionStructureQualityInspectorTest(
    AdsorptionQualityFixture,
    unittest.TestCase,
):
    def setUp(self):
        super().setUp()
        self.inspector = AdsorptionStructureQualityInspector()

    def _inspect_report(self):
        result = self.inspector.inspect([self.record])
        self.assertEqual(result["checked_count"], 1)
        return result, result["reports"][0]

    def _rewrite(self, atoms):
        write(
            self.record["poscar_path"],
            atoms,
            format="vasp",
            direct=True,
            sort=False,
            vasp5=True,
        )

    def test_valid_structure_passes(self):
        result, report = self._inspect_report()
        self.assertEqual(
            result["status"],
            "adsorption_quality_completed_all_passed",
        )
        self.assertEqual(report["quality_decision"], "passed")
        self.assertTrue(report["eligible_for_adsorption_review"])

    def test_coadsorption_metadata_is_rejected(self):
        record = dict(self.record)
        record["coadsorption"] = True
        result = self.inspector.inspect([record])
        self.assertEqual(result["error_count"], 1)
        self.assertIn(
            "one adsorbate instance",
            result["errors"][0]["message"],
        )

    def test_atom_count_mismatch_fails(self):
        metadata_path = self.root / "output" / "C12-QUALITY" / "S1" / "CO" / self.record["adsorption_structure_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["total_atom_count"] += 1
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        _, report = self._inspect_report()
        self.assertIn("atom_count", report["failed_checks"])

    def test_clean_coordinate_modification_fails(self):
        atoms = read(self.record["poscar_path"], format="vasp")
        atoms.positions[0, 0] += 0.1
        self._rewrite(atoms)
        _, report = self._inspect_report()
        self.assertIn("clean_coordinates", report["failed_checks"])

    def test_cell_modification_fails(self):
        atoms = read(self.record["poscar_path"], format="vasp")
        cell = atoms.cell.array.copy()
        cell[0, 0] += 0.1
        atoms.set_cell(cell, scale_atoms=False)
        self._rewrite(atoms)
        _, report = self._inspect_report()
        self.assertIn("cell", report["failed_checks"])

    def test_adsorbate_slab_collision_fails(self):
        atoms = read(self.record["poscar_path"], format="vasp")
        atoms.positions[-2] = atoms.positions[0]
        self._rewrite(atoms)
        _, report = self._inspect_report()
        self.assertIn(
            "adsorbate_slab_distance",
            report["failed_checks"],
        )

    def test_adsorbate_below_surface_fails(self):
        atoms = read(self.record["poscar_path"], format="vasp")
        clean_top = atoms.positions[:-2, 2].max()
        atoms.positions[-2:, 2] -= (
            atoms.positions[-2:, 2].min() - clean_top + 0.1
        )
        self._rewrite(atoms)
        _, report = self._inspect_report()
        self.assertIn(
            "adsorbate_above_surface",
            report["failed_checks"],
        )

    def test_anchor_moved_from_recorded_site_fails(self):
        atoms = read(self.record["poscar_path"], format="vasp")
        atoms.positions[-2:, 2] += 0.2
        self._rewrite(atoms)
        _, report = self._inspect_report()
        self.assertIn("anchor_height", report["failed_checks"])

    def test_missing_selective_dynamics_fails(self):
        atoms = read(self.record["poscar_path"], format="vasp")
        atoms.set_constraint()
        self._rewrite(atoms)
        _, report = self._inspect_report()
        self.assertIn(
            "clean_constraints_preserved",
            report["failed_checks"],
        )

    def test_fixed_adsorbate_fails(self):
        atoms = read(self.record["poscar_path"], format="vasp")
        atoms.set_constraint(
            FixAtoms(indices=[*range(32), len(atoms) - 1])
        )
        self._rewrite(atoms)
        _, report = self._inspect_report()
        self.assertIn("adsorbate_movable", report["failed_checks"])

    def test_result_is_json_serializable(self):
        json.dumps(
            self.inspector.inspect([self.record]),
            ensure_ascii=False,
        )


if __name__ == "__main__":
    unittest.main()
