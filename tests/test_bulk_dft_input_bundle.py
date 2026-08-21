import json
import tempfile
import unittest
from pathlib import Path

from app.domain.bulk_dft_input_bundle import (
    BulkFormationVaspBundleService,
)


class BulkFormationVaspBundleServiceTest(unittest.TestCase):
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
        self.output_root = self.root / "output"
        self.pbe_root = self.root / "PBE"
        self.config_path = self.root / "bulk.json"
        self.poscar_path = self.root / "bulk.vasp"
        self._write_config()
        self._write_potcars()
        self._write_poscar(self.COUNTS)
        self.service = BulkFormationVaspBundleService(
            output_root=self.output_root,
            config_path=self.config_path,
            pbe_root=self.pbe_root,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def queue_item(self) -> dict:
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
    def confirmations(bundle_id: str) -> dict:
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

    def test_empty_queue_is_skipped(self):
        result = self.service.preview([], "test")
        self.assertEqual(
            result["status"],
            "bulk_dft_input_preview_skipped",
        )

    def test_wrong_atom_count_is_rejected(self):
        self._write_poscar([7, 7, 6, 6, 5])
        with self.assertRaisesRegex(ValueError, "32 atoms"):
            self.service.preview([self.queue_item()], "test")

    def test_poscar_text_is_preserved(self):
        source = self.poscar_path.read_text(encoding="utf-8")
        result = self.service.preview([self.queue_item()], "test")
        self.assertEqual(
            result["bundles"][0]["preview"]["POSCAR"],
            source,
        )

    def test_bulk_poscar_without_selective_dynamics_is_supported(self):
        lines = self.poscar_path.read_text(
            encoding="utf-8"
        ).splitlines()
        lines.remove("Selective dynamics")
        self.poscar_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        result = self.service.preview([self.queue_item()], "test")

        self.assertEqual(
            result["status"],
            "bulk_dft_input_preview_completed",
        )

    def test_noble_metal_potcars_follow_poscar_order(self):
        result = self.service.preview([self.queue_item()], "test")
        plan = result["bundles"][0]["preview"]["POTCAR"]
        self.assertEqual(
            [item["element"] for item in plan],
            self.ELEMENTS,
        )
        self.assertEqual(
            [item["potential"] for item in plan],
            [self.MAPPING[element] for element in self.ELEMENTS],
        )

    def test_slurm_uses_configured_vasp_module(self):
        slurm = self.service.preview(
            [self.queue_item()],
            "test",
        )["bundles"][0]["preview"]["vasp.slurm"]

        self.assertEqual(
            slurm["module_name"],
            "vasp-test",
        )
        self.assertIn(
            "module load vasp-test",
            slurm["full_text"],
        )

    def test_finalize_creates_exactly_five_files(self):
        preview = self.service.preview([self.queue_item()], "test")
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
            sorted(BulkFormationVaspBundleService.FILE_NAMES),
        )
        self.assertEqual(
            job["status"],
            "bulk_dft_input_files_created",
        )
        identity = job["scientific_identity"]
        self.assertEqual(identity["structure_id"], "noble-bulk-01")
        self.assertEqual(identity["atom_count"], 32)
        self.assertEqual(sum(identity["composition"].values()), 32)
        self.assertEqual(identity["energy_field"], "final_toten_ev")
        self.assertEqual(
            Path(identity["source_poscar_path"]), self.poscar_path.resolve()
        )

    def test_result_is_json_serializable(self):
        result = self.service.preview([self.queue_item()], "test")
        self.assertIn(
            "bulk_dft_input_preview_completed",
            json.dumps(result, ensure_ascii=False),
        )

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

    def _write_poscar(self, counts: list[int]):
        coordinate_count = sum(counts)
        lines = [
            "C6D test bulk",
            "1.0",
            "4.0 0.0 0.0",
            "0.0 4.0 0.0",
            "0.0 0.0 4.0",
            " ".join(self.ELEMENTS),
            " ".join(str(value) for value in counts),
            "Selective dynamics",
            "Direct",
        ]
        for index in range(coordinate_count):
            value = index / max(coordinate_count, 1)
            lines.append(
                f"{value:.8f} {value:.8f} {value:.8f} T T T"
            )
        self.poscar_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    unittest.main()
