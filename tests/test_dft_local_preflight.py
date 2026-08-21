import json
import tempfile
import unittest
from pathlib import Path

from app.domain.bulk_dft_input_bundle import (
    BulkFormationVaspBundleService,
)
from app.domain.dft_local_preflight import (
    DFTLocalPreflightService,
)


class DFTLocalPreflightServiceTest(unittest.TestCase):
    ELEMENTS = ["Au", "Ag", "Pt", "Pd", "Cu"]
    COUNTS = [7, 7, 6, 6, 6]
    MAPPING = {
        "Au": "Au",
        "Ag": "Ag",
        "Pt": "Pt",
        "Pd": "Pd",
        "Cu": "Cu_pv",
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output_root = self.root / "approved_jobs"
        self.pbe_root = self.root / "PBE"
        self.config_path = self.root / "bulk.json"
        self.poscar_path = self.root / "source_bulk.vasp"

        self._write_config()
        self._write_potcars()
        self._write_poscar()

        bundle_service = BulkFormationVaspBundleService(
            output_root=self.output_root,
            config_path=self.config_path,
            pbe_root=self.pbe_root,
        )
        self.preview = bundle_service.preview(
            [self._queue_item()],
            task_id="c11-local-test",
        )
        bundle_id = self.preview["bundles"][0]["bundle_id"]
        finalized = bundle_service.finalize(
            self.preview,
            self._confirmations(bundle_id),
        )
        self.job = finalized["jobs"][0]
        self.job_dir = Path(self.job["job_dir"])
        self.service = DFTLocalPreflightService(
            allowed_roots=[self.output_root],
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_valid_five_files_pass(self):
        result = self._inspect()

        self.assertEqual(
            result["status"],
            "dft_local_preflight_passed",
        )
        self.assertEqual(result["passed_count"], 1)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(len(result["eligible_jobs"]), 1)
        self.assertFalse(result["submission_performed"])

    def test_crlf_source_poscar_matches_final_lf_poscar(self):
        source_text = self.poscar_path.read_text(encoding="utf-8")
        self.poscar_path.write_bytes(
            source_text.replace("\n", "\r\n").encode("utf-8")
        )

        result = self._inspect()

        self.assertEqual(
            result["status"],
            "dft_local_preflight_passed",
        )

    def test_changed_incar_fails(self):
        self._append_bytes("INCAR", b"ENCUT = 999\n")

        result = self._inspect()

        self.assert_failed_check(
            result,
            "INCAR_matches_reviewed_preview",
        )

    def test_changed_poscar_fails(self):
        self._append_bytes("POSCAR", b"\nchanged coordinate data\n")

        result = self._inspect()

        self.assert_failed_check(
            result,
            "POSCAR_matches_reviewed_preview",
        )
        self.assert_failed_check(
            result,
            "poscar_matches_source",
        )

    def test_changed_potcar_fails(self):
        self._append_bytes("POTCAR", b"changed-potcar")

        result = self._inspect()

        self.assert_failed_check(result, "potcar_content")

    def test_changed_potcar_source_is_rejected(self):
        source = self.pbe_root / "Au" / "POTCAR"
        source.write_bytes(source.read_bytes() + b"changed-source")

        result = self._inspect()

        self.assertEqual(
            result["status"],
            "dft_local_preflight_failed",
        )
        error = result["jobs"][0]["errors"][0]
        self.assertEqual(error["error_type"], "ValueError")
        self.assertIn("POTCAR source changed", error["message"])

    def test_extra_file_fails(self):
        (self.job_dir / "unexpected.txt").write_text(
            "unexpected",
            encoding="utf-8",
        )

        result = self._inspect()

        self.assert_failed_check(result, "exact_five_file_set")

    def test_empty_file_fails(self):
        (self.job_dir / "KPOINTS").write_bytes(b"")

        result = self._inspect()

        self.assert_failed_check(result, "KPOINTS_nonempty")

    def test_crlf_slurm_fails(self):
        path = self.job_dir / "vasp.slurm"
        content = path.read_bytes().replace(b"\n", b"\r\n")
        path.write_bytes(content)

        result = self._inspect()

        self.assert_failed_check(
            result,
            "vasp.slurm_matches_reviewed_preview",
        )
        self.assert_failed_check(
            result,
            "vasp.slurm_uses_lf",
        )

    def test_windows_path_in_slurm_fails(self):
        path = self.job_dir / "vasp.slurm"
        original = path.read_bytes()
        path.write_bytes(original + b"source C:\\vasp\\env.sh\n")

        result = self._inspect()

        self.assert_failed_check(
            result,
            "slurm_has_no_windows_path",
        )

    def test_job_directory_outside_allowed_root_fails(self):
        service = DFTLocalPreflightService(
            allowed_roots=[self.root / "different_root"],
        )

        result = service.inspect(
            jobs=[self.job],
            preview=self.preview,
            job_source="c6d_bulk_formation",
        )

        self.assert_failed_check(
            result,
            "job_directory_allowed",
        )

    def test_missing_preview_bundle_fails(self):
        result = self.service.inspect(
            jobs=[self.job],
            preview={"bundles": []},
            job_source="c6d_bulk_formation",
        )

        self.assertEqual(
            result["status"],
            "dft_local_preflight_failed",
        )
        self.assertEqual(
            result["jobs"][0]["errors"][0]["error_type"],
            "ValueError",
        )

    def test_empty_jobs_are_skipped(self):
        result = self.service.inspect(
            jobs=[],
            preview=self.preview,
            job_source="c6d_bulk_formation",
        )

        self.assertEqual(
            result["status"],
            "dft_local_preflight_skipped",
        )
        self.assertEqual(result["job_count"], 0)

    def test_result_is_json_serializable(self):
        text = json.dumps(
            self._inspect(),
            ensure_ascii=False,
        )

        self.assertIn("dft_local_preflight_passed", text)

    def test_clean_slab_requires_48_atoms(self):
        checks = []
        errors = []

        self.service._check_structure_identity(
            checks=checks,
            errors=errors,
            job={},
            job_source="c10_slab",
            elements=["Cu"],
            counts=[48],
        )

        self.assertEqual(errors, [])

    def test_single_adsorbate_uses_scientific_identity_atom_count(self):
        checks = []
        errors = []
        job = {
            "adsorbate_instance_count": 1,
            "coadsorption": False,
            "scientific_identity": {
                "atom_count": 50,
                "adsorbate_instance_count": 1,
                "coadsorption": False,
                "composition": {"Cu": 48, "C": 1, "O": 1},
            },
        }

        self.service._check_structure_identity(
            checks=checks,
            errors=errors,
            job=job,
            job_source="c12_5_adsorption",
            elements=["Cu", "C", "O"],
            counts=[48, 1, 1],
        )

        self.assertEqual(errors, [])

    def test_adsorbate_atom_count_is_dynamic(self):
        cases = [
            ({"Cu": 48, "H": 1}, 49),
            ({"Cu": 48, "O": 1, "H": 1}, 50),
            ({"Cu": 48, "O": 2, "H": 1}, 51),
            ({"Cu": 48, "C": 1, "O": 2, "H": 1}, 52),
        ]

        for composition, atom_count in cases:
            with self.subTest(atom_count=atom_count):
                checks = []
                errors = []
                job = {
                    "adsorbate_instance_count": 1,
                    "coadsorption": False,
                    "scientific_identity": {
                        "atom_count": atom_count,
                        "adsorbate_instance_count": 1,
                        "coadsorption": False,
                        "composition": composition,
                    },
                }

                self.service._check_structure_identity(
                    checks=checks,
                    errors=errors,
                    job=job,
                    job_source="c12_5_adsorption",
                    elements=list(composition),
                    counts=list(composition.values()),
                )

                self.assertEqual(errors, [])

    def test_adsorbate_poscar_must_match_scientific_identity(self):
        checks = []
        errors = []
        job = {
            "adsorbate_instance_count": 1,
            "coadsorption": False,
            "scientific_identity": {
                "atom_count": 50,
                "adsorbate_instance_count": 1,
                "coadsorption": False,
                "composition": {"Cu": 48, "C": 1, "O": 1},
            },
        }

        self.service._check_structure_identity(
            checks=checks,
            errors=errors,
            job=job,
            job_source="c12_5_adsorption",
            elements=["Cu", "C", "O"],
            counts=[47, 1, 1],
        )

        failed_checks = {error["check"] for error in errors}
        self.assertEqual(
            failed_checks,
            {
                "poscar_composition_matches_identity",
                "poscar_atom_count",
            },
        )

    def _inspect(self) -> dict:
        return self.service.inspect(
            jobs=[self.job],
            preview=self.preview,
            job_source="c6d_bulk_formation",
        )

    def _queue_item(self) -> dict:
        return {
            "job_type": "formation_energy_dft",
            "status": "waiting_for_supercomputer",
            "structure_id": "noble-bulk-01",
            "candidate_id": "C1",
            "elements": self.ELEMENTS,
            "composition": dict(zip(self.ELEMENTS, self.COUNTS)),
            "poscar_path": str(self.poscar_path),
        }

    @staticmethod
    def _confirmations(bundle_id: str) -> dict:
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

    def _write_config(self):
        value = {
            "incar": {
                "LWAVE": "F",
                "LCHARG": "F",
                "ENCUT": 400,
                "NELM": 200,
                "NSW": 800,
                "EDIFFG": -0.03,
            },
            "kpoints": [
                "Automatic Mesh",
                "0",
                "Gamma",
                "1  1  1",
                "0  0  0",
            ],
            "magnetic_elements": ["Fe", "Co", "Ni", "Mn"],
            "magmom_per_atom": 0.5,
            "potcar_mapping": self.MAPPING,
            "slurm": {
                "nodes": 1,
                "tasks_per_node": 32,
                "partition": "normal",
                "module_name": "vasp-test",
                "command": "srun vasp_std",
            },
        }
        self.config_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_potcars(self):
        for element, potential in self.MAPPING.items():
            directory = self.pbe_root / potential
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "POTCAR").write_bytes(
                f"POTCAR-{element}-{potential}\n".encode("ascii")
            )

    def _write_poscar(self):
        atom_count = sum(self.COUNTS)
        lines = [
            "C11.2 test bulk",
            "1.0",
            "4.0 0.0 0.0",
            "0.0 4.0 0.0",
            "0.0 0.0 4.0",
            " ".join(self.ELEMENTS),
            " ".join(str(value) for value in self.COUNTS),
            "Selective dynamics",
            "Direct",
        ]
        for index in range(atom_count):
            value = index / atom_count
            lines.append(
                f"{value:.8f} {value:.8f} {value:.8f} T T T"
            )
        self.poscar_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def _append_bytes(self, name: str, value: bytes):
        path = self.job_dir / name
        path.write_bytes(path.read_bytes() + value)

    def assert_failed_check(
        self,
        result: dict,
        expected_check: str,
    ) -> None:
        self.assertEqual(
            result["status"],
            "dft_local_preflight_failed",
        )
        failed_checks = {
            error.get("check")
            for error in result["jobs"][0]["errors"]
        }
        self.assertIn(expected_check, failed_checks)


if __name__ == "__main__":
    unittest.main()
