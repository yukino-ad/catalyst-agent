import json
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock

from app.domain.cgcnn_training_manager import CGCNNTrainingManager


class InlineExecutor:
    def submit(self, function, *args, **kwargs):
        future = Future()
        try:
            future.set_result(function(*args, **kwargs))
        except Exception as error:
            future.set_exception(error)
        return future


class CGCNNTrainingManagerTest(unittest.TestCase):
    def test_task_training_is_persisted_without_production_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "database" / "750-Formation-regression-t-v-t"
            dataset.mkdir(parents=True)
            (dataset / "atom_init.json").write_text("{}", encoding="utf-8")
            for split in ("train", "val", "test"):
                cif = f"{split}.cif"
                (dataset / cif).write_text("data_test\n", encoding="utf-8")
                (dataset / f"{split}.csv").write_text(f"{cif},-0.1\n", encoding="utf-8")
            candidate = root / "candidate.cif"
            candidate.write_text("data_candidate\n", encoding="utf-8")
            experiment = root / "experiment"
            experiment.mkdir()
            model = experiment / "model_best.pth.tar"
            model.write_bytes(b"checkpoint")

            service = Mock()
            service.dataset_dir = dataset
            service.train.return_value = {
                "model_path": str(model),
                "metrics": {"mae": 0.02, "rmse": 0.03, "r2": 0.8},
                "promoted_to_production": False,
            }
            service.predict_with_model.return_value = [{
                "formation_energy_per_atom": -0.05,
                "unit": "eV/atom",
            }]
            manager = CGCNNTrainingManager(
                project_root=root,
                service=service,
                executor=InlineExecutor(),
            )
            started = manager.start("task-1", [{
                "structure_id": "S1",
                "cif_path": str(candidate),
            }])
            completed = manager.get("task-1", started["run_id"])

            self.assertEqual(completed["status"], "completed")
            self.assertFalse(completed["production_model_replaced"])
            service.train.assert_called_once()
            self.assertFalse(service.train.call_args.kwargs["promote_if_better"])
            predictions = manager.predictions("task-1", started["run_id"])
            self.assertEqual(predictions[0]["structure_id"], "S1")
            metadata = json.loads(
                (manager._run_dir("task-1", started["run_id"]) / "training_metadata.json")
                .read_text(encoding="utf-8")
            )
            self.assertFalse(metadata["production_model_replaced"])

    def test_dataset_overlap_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory)
            (dataset / "same.cif").write_text("data_same\n", encoding="utf-8")
            for split in ("train", "val", "test"):
                (dataset / f"{split}.csv").write_text("same.cif,-0.1\n", encoding="utf-8")
            manager = CGCNNTrainingManager(project_root=dataset.parent, service=Mock())
            with self.assertRaisesRegex(ValueError, "重复 CIF"):
                manager._validate_dataset(dataset)


if __name__ == "__main__":
    unittest.main()
