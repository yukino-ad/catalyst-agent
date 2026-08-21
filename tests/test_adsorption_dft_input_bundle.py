import json
import tempfile
import unittest
from pathlib import Path

from app.domain.adsorption_dft_input_bundle import (
    AdsorptionVaspInputBundleService,
)
from app.domain.dft_input_revision import (
    DFTInputRevisionError,
    DFTInputRevisionService,
)


class AdsorptionVaspInputBundleServiceTest(unittest.TestCase):
    BASE_ELEMENTS = ["Cu", "Co", "Fe", "Mn", "Al"]
    BASE_COUNTS = [10, 10, 10, 10, 8]
    POTCAR_MAPPING = {
        "Cu": "Cu_pv",
        "Co": "Co_pv",
        "Fe": "Fe_pv",
        "Mn": "Mn_pv",
        "Al": "Al",
        "H": "H",
        "C": "C",
        "O": "O",
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output_root = self.root / "outputs"
        self.pbe_root = self.root / "PBE"
        self.config_path = self.root / "adsorption.json"
        self._write_config()
        self._write_potcars()
        self.service = AdsorptionVaspInputBundleService(
            output_root=self.output_root,
            config_path=self.config_path,
            pbe_root=self.pbe_root,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _structure(self, identifier, adsorbate, symbols):
        directory = self.root / identifier
        directory.mkdir()
        elements = self.BASE_ELEMENTS + list(dict.fromkeys(symbols))
        extra_counts = [symbols.count(element) for element in elements[5:]]
        counts = self.BASE_COUNTS + extra_counts
        atom_count = sum(counts)
        poscar = directory / "POSCAR"
        metadata = directory / "metadata.json"
        self._write_poscar(poscar, elements, counts)
        metadata.write_text(
            json.dumps({
                "total_atom_count": atom_count,
                "adsorbate": adsorbate,
                "adsorbate_instance_count": 1,
                "coadsorption": False,
            }),
            encoding="utf-8",
        )
        return {
            "adsorption_structure_id": identifier,
            "candidate_id": "C1",
            "slab_id": "clean-slab-1",
            "site_id": "site-1",
            "site_type": "ontop",
            "adsorbate": adsorbate,
            "adsorbate_instance_count": 1,
            "coadsorption": False,
            "eligible_for_adsorption_review": True,
            "adsorption_review_status": (
                "approved_for_adsorption_dft"
            ),
            "poscar_path": str(poscar),
            "metadata_path": str(metadata),
        }

    @staticmethod
    def _confirm(bundle_id):
        return {
            "action": "finalize",
            "approve": [bundle_id],
            "reject": [],
            "defer": [],
            "file_confirmations": {
                bundle_id: {
                    "POSCAR": True,
                    "INCAR": True,
                    "KPOINTS": True,
                    "POTCAR": True,
                    "vasp.slurm": True,
                }
            },
        }

    def test_unapproved_structure_is_rejected(self):
        structure = self._structure("H-unapproved", "H", ["H"])
        structure["adsorption_review_status"] = "deferred"
        with self.assertRaisesRegex(ValueError, "not approved"):
            self.service.preview([structure], "task")

    def test_coadsorption_is_rejected(self):
        structure = self._structure("H-coadsorption", "H", ["H"])
        structure["coadsorption"] = True
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.service.preview([structure], "task")

    def test_49_50_and_52_atom_structures_are_supported(self):
        structures = [
            self._structure("H-49", "H", ["H"]),
            self._structure("CO-50", "CO", ["C", "O"]),
            self._structure(
                "COOH-52",
                "COOH",
                ["C", "O", "O", "H"],
            ),
        ]
        result = self.service.preview(structures, "atom-counts")
        self.assertEqual(
            [bundle["atom_count"] for bundle in result["bundles"]],
            [49, 50, 52],
        )

    def test_potcar_follows_poscar_element_order(self):
        structure = self._structure("CO-order", "CO", ["C", "O"])
        bundle = self.service.preview([structure], "order")["bundles"][0]
        self.assertEqual(
            [item["element"] for item in bundle["preview"]["POTCAR"]],
            self.BASE_ELEMENTS + ["C", "O"],
        )

    def test_preview_does_not_write_formal_directory(self):
        structure = self._structure("H-preview", "H", ["H"])
        result = self.service.preview([structure], "preview-only")
        self.assertFalse(result["formal_files_written"])
        self.assertFalse(self.output_root.exists())

    def test_incomplete_confirmation_writes_nothing(self):
        structure = self._structure("H-incomplete", "H", ["H"])
        preview = self.service.preview([structure], "incomplete")
        bundle_id = preview["bundles"][0]["bundle_id"]
        decision = self._confirm(bundle_id)
        decision["file_confirmations"][bundle_id]["KPOINTS"] = False
        result = self.service.finalize(preview, decision)
        self.assertEqual(result["prepared_job_count"], 0)
        self.assertFalse(self.output_root.exists())

    def test_finalize_writes_exactly_five_files(self):
        structure = self._structure("CO-final", "CO", ["C", "O"])
        preview = self.service.preview([structure], "finalize")
        bundle_id = preview["bundles"][0]["bundle_id"]
        result = self.service.finalize(
            preview,
            self._confirm(bundle_id),
        )
        job = result["jobs"][0]
        self.assertEqual(job["file_count"], 5)
        self.assertEqual(job["job_source"], "c12_5_adsorption")
        self.assertEqual(
            sorted(path.name for path in Path(job["job_dir"]).iterdir()),
            sorted(self.service.FILE_NAMES),
        )

    def test_changed_potcar_after_preview_is_rejected(self):
        structure = self._structure("H-changed", "H", ["H"])
        preview = self.service.preview([structure], "changed")
        bundle_id = preview["bundles"][0]["bundle_id"]
        source = self.pbe_root / "H" / "POTCAR"
        source.write_bytes(source.read_bytes() + b"changed")
        result = self.service.finalize(
            preview,
            self._confirm(bundle_id),
        )
        self.assertEqual(result["prepared_job_count"], 0)
        self.assertIn("changed after preview", result["failures"][0]["message"])

    def test_poscar_revision_is_rejected(self):
        revision = DFTInputRevisionService(bundle_service=self.service)
        with self.assertRaisesRegex(DFTInputRevisionError, "POSCAR"):
            revision._validate_changes({"POSCAR": {"move": "atom"}})

    def test_result_is_json_serializable(self):
        structure = self._structure("H-json", "H", ["H"])
        json.dumps(
            self.service.preview([structure], "json"),
            ensure_ascii=False,
        )

    def _write_config(self):
        value = {
            "incar": {
                "ENCUT": 400,
                "NSW": 100,
                "IBRION": 2,
            },
            "kpoints": [
                "Automatic Mesh",
                "0",
                "Gamma",
                "1  1  1",
                "0  0  0",
            ],
            "magnetic_elements": ["Fe", "Co", "Mn"],
            "potcar_mapping": self.POTCAR_MAPPING,
            "slurm": {
                "nodes": 1,
                "tasks_per_node": 32,
                "partition": "test",
                "module_name": "vasp-test",
                "command": "srun vasp_std",
            },
        }
        self.config_path.write_text(
            json.dumps(value),
            encoding="utf-8",
        )

    def _write_potcars(self):
        for potential in set(self.POTCAR_MAPPING.values()):
            directory = self.pbe_root / potential
            directory.mkdir(parents=True)
            (directory / "POTCAR").write_bytes(
                f"POTCAR-{potential}\n".encode("ascii")
            )

    @staticmethod
    def _write_poscar(path, elements, counts):
        coordinate_count = sum(counts)
        lines = [
            "adsorption-test",
            "1.0",
            "10.0 0.0 0.0",
            "0.0 10.0 0.0",
            "0.0 0.0 30.0",
            " ".join(elements),
            " ".join(str(value) for value in counts),
            "Selective dynamics",
            "Direct",
        ]
        lines.extend(
            f"0.1 0.1 {0.1 + index * 0.001:.6f} T T T"
            for index in range(coordinate_count)
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
