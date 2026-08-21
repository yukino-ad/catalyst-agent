import json
import tempfile
import unittest
from pathlib import Path

from app.domain.dft_input_bundle import (
    VaspInputBundleService,
)


class VaspInputBundleServiceTest(unittest.TestCase):
    ELEMENTS = ["Cu", "Co", "Fe", "Mn", "Al"]
    COUNTS = [10, 10, 10, 10, 8]
    MAPPING = {
        "Cu": "Cu_pv",
        "Co": "Co_pv",
        "Fe": "Fe_pv",
        "Mn": "Mn_pv",
        "Al": "Al",
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output_root = self.root / "dft_inputs"
        self.pbe_root = self.root / "PBE"
        self.config_path = self.root / "vasp.json"
        self.poscar_path = self.root / "approved.vasp"

        self._write_config()
        self._write_fake_potcars()
        self._write_poscar()

        self.service = VaspInputBundleService(
            output_root=self.output_root,
            config_path=self.config_path,
            pbe_root=self.pbe_root,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def approved_slab(self) -> dict:
        return {
            "slab_id": "C10-TEST-slab111",
            "candidate_id": "C1",
            "poscar_path": str(self.poscar_path),
            "quality_decision": "passed",
            "eligible_for_dft_review": True,
            "slab_review_status": "approved_for_dft",
        }

    def preview(self) -> dict:
        return self.service.preview(
            [self.approved_slab()],
            task_id="c10-test",
        )

    @staticmethod
    def confirmations(bundle_id: str) -> dict:
        return {
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
            "note": "approved in test",
        }

    def test_preview_does_not_write_formal_directory(self):
        result = self.preview()

        self.assertEqual(
            result["status"],
            "dft_input_preview_completed",
        )
        self.assertFalse(result["formal_files_written"])
        self.assertFalse(self.output_root.exists())

    def test_preview_preserves_poscar_element_order(self):
        bundle = self.preview()["bundles"][0]

        self.assertEqual(bundle["elements"], self.ELEMENTS)
        self.assertEqual(
            [item["element"] for item in bundle["preview"]["POTCAR"]],
            self.ELEMENTS,
        )
        self.assertEqual(
            [item["potential"] for item in bundle["preview"]["POTCAR"]],
            [self.MAPPING[element] for element in self.ELEMENTS],
        )

    def test_slurm_uses_configured_vasp_module(self):
        slurm = self.preview()["bundles"][0][
            "preview"
        ]["vasp.slurm"]

        self.assertEqual(
            slurm["module_name"],
            "vasp-test",
        )
        self.assertIn(
            "module load vasp-test",
            slurm["full_text"],
        )
        self.assertNotIn(
            "/work/home/chenheli",
            slurm["full_text"],
        )

    def test_finalize_creates_exactly_five_files(self):
        preview = self.preview()
        bundle_id = preview["bundles"][0]["bundle_id"]

        result = self.service.finalize(
            preview,
            self.confirmations(bundle_id),
        )

        self.assertEqual(
            result["status"],
            "dft_input_preparation_completed",
        )
        job = result["jobs"][0]
        files = sorted(
            path.name
            for path in Path(job["job_dir"]).iterdir()
            if path.is_file()
        )
        self.assertEqual(
            files,
            sorted(VaspInputBundleService.FILE_NAMES),
        )
        self.assertEqual(job["file_count"], 5)

        expected_potcar = b"".join(
            (self.pbe_root / self.MAPPING[element] / "POTCAR").read_bytes()
            for element in self.ELEMENTS
        )
        self.assertEqual(
            Path(job["files"]["POTCAR"]).read_bytes(),
            expected_potcar,
        )

    def test_incomplete_confirmation_is_rejected(self):
        preview = self.preview()
        bundle_id = preview["bundles"][0]["bundle_id"]
        decision = self.confirmations(bundle_id)
        decision["file_confirmations"][bundle_id]["KPOINTS"] = False

        result = self.service.finalize(preview, decision)

        self.assertEqual(
            result["status"],
            "dft_input_preparation_failed",
        )
        self.assertEqual(result["prepared_job_count"], 0)
        self.assertFalse(self.output_root.joinpath("c10-test", bundle_id).exists())

    def test_unapproved_slab_is_rejected(self):
        slab = self.approved_slab()
        slab["slab_review_status"] = "deferred"

        with self.assertRaisesRegex(ValueError, "C9-approved"):
            self.service.preview([slab], task_id="c10-test")

    def test_changed_potcar_is_rejected(self):
        preview = self.preview()
        bundle_id = preview["bundles"][0]["bundle_id"]
        source = self.pbe_root / "Cu_pv" / "POTCAR"
        source.write_bytes(source.read_bytes() + b"changed")

        result = self.service.finalize(
            preview,
            self.confirmations(bundle_id),
        )

        self.assertEqual(
            result["status"],
            "dft_input_preparation_failed",
        )
        self.assertIn("changed after preview", result["failures"][0]["message"])

    def test_existing_directory_is_not_overwritten(self):
        preview = self.preview()
        bundle_id = preview["bundles"][0]["bundle_id"]
        decision = self.confirmations(bundle_id)

        first = self.service.finalize(preview, decision)
        second = self.service.finalize(preview, decision)

        self.assertEqual(
            first["status"],
            "dft_input_preparation_completed",
        )
        self.assertEqual(
            second["status"],
            "dft_input_preparation_failed",
        )
        self.assertIn("already exists", second["failures"][0]["message"])

    def test_result_is_json_serializable(self):
        text = json.dumps(self.preview(), ensure_ascii=False)
        self.assertIn("dft_input_preview_completed", text)

    def _write_config(self):
        value = {
            "incar": {
                "LWAVE": "F",
                "LCHARG": "F",
                "ENCUT": 400,
                "NSW": 100,
            },
            "kpoints": [
                "Automatic Mesh",
                "0",
                "Gamma",
                "1  1  1",
                "0  0  0",
            ],
            "magnetic_elements": ["Fe", "Co", "Ni", "Mn", "Cr"],
            "potcar_mapping": self.MAPPING,
            "slurm": {
                "nodes": 1,
                "tasks_per_node": 32,
                "partition": "xahcnormal",
                "module_name": "vasp-test",
                "command": "srun --mpi=pmi2 vasp_std",
            },
        }
        self.config_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_fake_potcars(self):
        for element, potential in self.MAPPING.items():
            directory = self.pbe_root / potential
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "POTCAR").write_bytes(
                f"POTCAR-{element}-{potential}\n".encode("ascii")
            )

    def _write_poscar(self):
        coordinates = []
        for index in range(48):
            x = (index % 4) / 4
            y = ((index // 4) % 4) / 4
            z = (index // 16) / 10
            flag = "T T T" if index >= 32 else "F F F"
            coordinates.append(
                f"{x:.8f} {y:.8f} {z:.8f} {flag}"
            )

        lines = [
            "C10_TEST_SLAB",
            "1.0",
            "10.0 0.0 0.0",
            "0.0 10.0 0.0",
            "0.0 0.0 20.0",
            " ".join(self.ELEMENTS),
            " ".join(str(value) for value in self.COUNTS),
            "Selective dynamics",
            "Direct",
            *coordinates,
        ]
        self.poscar_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
