import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.domain.dft_input_bundle import VaspInputBundleService
from app.domain.dft_input_revision import (
    DFTInputRevisionError,
    DFTInputRevisionService,
)


class DFTInputRevisionServiceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.config = root / "vasp.json"
        self.pbe = root / "PBE"
        mapping = {"Cu": "Cu_pv", "Co": "Co_pv"}
        self.config.write_text(json.dumps({
            "incar": {"ENCUT": 400, "NSW": 100},
            "kpoints": ["Automatic Mesh", "0", "Gamma", "1  1  1", "0  0  0"],
            "magnetic_elements": ["Co"],
            "potcar_mapping": mapping,
            "slurm": {
                "nodes": 1,
                "tasks_per_node": 32,
                "partition": "normal",
                "module_name": "vasp-test",
                "command": "srun vasp_std",
            },
        }), encoding="utf-8")
        for potential in mapping.values():
            directory = self.pbe / potential
            directory.mkdir(parents=True)
            (directory / "POTCAR").write_text(potential, encoding="ascii")
        self.bundle_service = VaspInputBundleService(
            config_path=self.config,
            pbe_root=self.pbe,
        )
        self.service = DFTInputRevisionService(
            bundle_service=self.bundle_service,
            llm=Mock(available=True),
        )
        poscar = "fixed coordinates\n"
        incar = "SYSTEM = Cu-Co\n\nENCUT   = 400\nNSW     = 100\n"
        kpoints = "Automatic Mesh\n0\nGamma\n1  1  1\n0  0  0\n"
        config = self.bundle_service._load_config()
        potcar = self.bundle_service._potcar_plan(["Cu", "Co"], config)
        slurm = self.bundle_service._build_slurm("S1", config)
        digest = self.bundle_service._preview_digest(
            poscar, incar, kpoints, slurm, potcar
        )
        self.preview = {
            "bundles": [{
                "bundle_id": "S1",
                "elements": ["Cu", "Co"],
                "preview_version": 1,
                "preview_digest": digest,
                "preview": {
                    "POSCAR": poscar,
                    "INCAR": incar,
                    "KPOINTS": kpoints,
                    "POTCAR": potcar,
                    "vasp.slurm": {
                        "job_name": "S1",
                        "nodes": 1,
                        "tasks_per_node": 32,
                        "partition": "normal",
                        "module_name": "vasp-test",
                        "command": "srun vasp_std",
                        "full_text": slurm,
                    },
                },
            }]
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_valid_revision_preserves_poscar_and_records_history(self):
        old_poscar = self.preview["bundles"][0]["preview"]["POSCAR"]
        old_digest = self.preview["bundles"][0]["preview_digest"]
        result = self.service.apply(self.preview, {
            "plans": [{
                "bundle_id": "S1",
                "request": "ENCUT 500 and 3x3x1",
                "changes": {
                    "INCAR": {"ENCUT": 500},
                    "KPOINTS": {"mesh": [3, 3, 1]},
                },
            }]
        })
        bundle = result["preview"]["bundles"][0]
        self.assertEqual(bundle["preview"]["POSCAR"], old_poscar)
        self.assertIn("ENCUT   = 500", bundle["preview"]["INCAR"])
        self.assertIn("3  3  1", bundle["preview"]["KPOINTS"])
        self.assertNotEqual(bundle["preview_digest"], old_digest)
        self.assertEqual(bundle["preview_version"], 2)
        self.assertTrue(result["history"][0]["poscar_unchanged"])

    def test_poscar_change_is_rejected(self):
        with self.assertRaisesRegex(DFTInputRevisionError, "POSCAR"):
            self.service.apply(self.preview, {
                "plans": [{"bundle_id": "S1", "changes": {"POSCAR": {"coordinates": []}}}]
            })

    def test_unknown_incar_key_is_rejected(self):
        with self.assertRaisesRegex(DFTInputRevisionError, "Unsupported INCAR"):
            self.service.apply(self.preview, {
                "plans": [{"bundle_id": "S1", "changes": {"INCAR": {"UNKNOWN": 1}}}]
            })

    def test_shell_injection_is_rejected(self):
        with self.assertRaisesRegex(DFTInputRevisionError, "Unsafe"):
            self.service.apply(self.preview, {
                "plans": [{"bundle_id": "S1", "changes": {"vasp.slurm": {"partition": "normal; rm"}}}]
            })

    def test_missing_potcar_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            self.service.apply(self.preview, {
                "plans": [{"bundle_id": "S1", "changes": {"POTCAR": {"Cu": "missing"}}}]
            })

    def test_potcar_path_escape_is_rejected(self):
        with self.assertRaisesRegex(DFTInputRevisionError, "Unsafe POTCAR"):
            self.service.apply(self.preview, {
                "plans": [{"bundle_id": "S1", "changes": {"POTCAR": {"Cu": "../outside"}}}]
            })

    def test_incar_newline_is_rejected(self):
        with self.assertRaisesRegex(DFTInputRevisionError, "Unsafe INCAR"):
            self.service.apply(self.preview, {
                "plans": [{"bundle_id": "S1", "changes": {"INCAR": {"ENCUT": "500\nBAD=1"}}}]
            })

    def test_maximum_revision_count_is_enforced(self):
        with self.assertRaisesRegex(DFTInputRevisionError, "Maximum"):
            self.service.apply(self.preview, {"plans": []}, revision_count=5)

    def test_raw_poscar_request_is_rejected_before_llm(self):
        with self.assertRaisesRegex(DFTInputRevisionError, "POSCAR"):
            self.service.parse_requests(
                {"S1": "请修改 POSCAR 坐标"}, self.preview
            )


if __name__ == "__main__":
    unittest.main()
