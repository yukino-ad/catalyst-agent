import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from tools.cgcnn_service import CGCNNService
from tools.ovito_service import OvitoService


class CGCNNServiceTest(unittest.TestCase):
    def test_prediction_dataset_uses_cgcnn_layout(self):
        service = CGCNNService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cif"
            source.write_text("data_test\n", encoding="utf-8")
            service.prediction_dir = root / "prediction"
            with patch.object(service, "dataset_dir", root):
                (root / "atom_init.json").write_text("{}", encoding="utf-8")
                service._prepare_prediction_dataset([source])
            self.assertTrue((service.prediction_dir / "agent_candidate_0001.cif").is_file())
            self.assertEqual(
                (service.prediction_dir / "id_prop.csv").read_text(encoding="utf-8").strip(),
                "agent_candidate_0001,0.0",
            )

    def test_production_metrics_reads_current_model_metadata(self):
        service = CGCNNService()
        with tempfile.TemporaryDirectory() as directory:
            service.artifact_dir = Path(directory)
            service.metadata_path.write_text(
                json.dumps({"metrics": {"mae": 0.02, "rmse": 0.03, "r2": 0.9}}),
                encoding="utf-8",
            )
            self.assertEqual(service.production_metrics()["mae"], 0.02)

    def test_ovito_opens_only_first_file(self):
        service = OvitoService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service.executable = root / "ovito.exe"
            service.executable.write_text("placeholder", encoding="utf-8")
            files = []
            for index in range(12):
                path = root / f"POSCAR_{index}.vasp"
                path.write_text("placeholder", encoding="utf-8")
                files.append(path)
            with patch("tools.ovito_service.subprocess.Popen") as popen:
                result = service.open_structures(files)
            self.assertEqual(result["opened_count"], 1)
            self.assertTrue(result["truncated"])
            self.assertEqual(len(popen.call_args.args[0]) - 1, 1)


if __name__ == "__main__":
    unittest.main()
