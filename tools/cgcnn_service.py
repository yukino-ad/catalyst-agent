from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence


LogCallback = Callable[[str], None]


class CGCNNService:
    """Train and run the bundled CGCNN formation-energy model."""

    def __init__(
        self,
        project_root: str | Path | None = None,
        python_executable: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
        self.cgcnn_dir = self.project_root / "models" / "cgcnn-master"
        self.dataset_dir = self.project_root / "database" / "750-Formation-regression-t-v-t"
        self.artifact_dir = self.project_root / "models" / "formation-energy-cgcnn"
        self.prediction_dir = self.project_root / "data" / "cgcnn_prediction"
        self.python_executable = Path(
            python_executable or self._configured_python() or sys.executable
        )
        self.site_packages = self.cgcnn_dir / "venv" / "Lib" / "site-packages"

    @property
    def model_path(self) -> Path:
        return self.artifact_dir / "model_best.pth.tar"

    @property
    def metadata_path(self) -> Path:
        return self.artifact_dir / "training_metadata.json"

    def train(
        self,
        epochs: int = 60,
        batch_size: int = 32,
        learning_rate: float = 0.001,
        atom_fea_len: int = 64,
        h_fea_len: int = 128,
        n_conv: int = 3,
        experiment_name: str | None = None,
        log_callback: LogCallback | None = None,
        promote_if_better: bool = True,
    ) -> dict[str, Any]:
        self._validate_layout(training=True)
        self._validate_python()
        if epochs <= 0:
            raise ValueError("CGCNN 训练轮数必须大于 0。")

        name = experiment_name or datetime.now().strftime("run_%Y%m%d_%H%M%S")
        run_dir = self.artifact_dir / "experiments" / name
        run_dir.mkdir(parents=True, exist_ok=False)
        command = [
            str(self.python_executable), "-u", str(self.cgcnn_dir / "main-r.py"),
            "--split-mode", "manual",
            "--train-file", "train.csv",
            "--val-file", "val.csv",
            "--test-file", "test.csv",
            "--epochs", str(epochs),
            "--batch-size", str(batch_size),
            "--lr", str(learning_rate),
            "--atom-fea-len", str(atom_fea_len),
            "--h-fea-len", str(h_fea_len),
            "--n-conv", str(n_conv),
            "--workers", "0", "--task", "regression", "--optim", "Adam",
            "--disable-cuda", str(self.dataset_dir),
        ]
        self._emit(log_callback, f"训练目录: {run_dir}")
        self._emit(log_callback, f"训练参数: epochs={epochs}, batch={batch_size}, lr={learning_rate}")
        log_text = self._run_stream(command, run_dir, log_callback)

        run_model = run_dir / "model_best.pth.tar"
        if not run_model.is_file():
            raise RuntimeError("训练结束，但没有生成 model_best.pth.tar。")
        metrics = self._regression_metrics(run_dir / "test_results.csv")
        old_metrics = self.production_metrics()
        promoted = bool(
            promote_if_better
            and metrics.get("mae") is not None
            and (old_metrics.get("mae") is None or metrics["mae"] < old_metrics["mae"])
        )

        metadata = {
            "property": "formation_energy_per_atom",
            "unit": "eV/atom",
            "dataset": str(self.dataset_dir),
            "split": {"train": 560, "validation": 70, "test": 70},
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "atom_fea_len": atom_fea_len,
            "h_fea_len": h_fea_len,
            "n_conv": n_conv,
            "metrics": metrics,
            "previous_production_metrics": old_metrics,
            "experiment_model_path": str(run_model.resolve()),
            "promoted_to_production": promoted,
            "stdout_tail": log_text[-4000:],
        }
        run_metadata = run_dir / "training_metadata.json"
        run_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        if promoted:
            self._promote(run_dir, metadata)
            self._emit(log_callback, "新模型测试 MAE 更低，已晋升为生产模型。")
        else:
            self._emit(log_callback, "新模型已保留，但未优于生产模型，因此未替换默认模型。")
        metadata["model_path"] = str(run_model.resolve())
        metadata["production_model_path"] = str(self.model_path.resolve())
        return metadata

    def production_metrics(self) -> dict[str, float]:
        if not self.metadata_path.is_file():
            return {}
        try:
            return json.loads(self.metadata_path.read_text(encoding="utf-8")).get("metrics", {})
        except (OSError, json.JSONDecodeError):
            return {}

    def predict(self, cif_paths: Sequence[str | Path]) -> list[dict[str, Any]]:
        return self.predict_with_model(
            cif_paths,
            model_path=self.model_path,
            prediction_dir=self.prediction_dir,
        )

    def predict_with_model(
        self,
        cif_paths: Sequence[str | Path],
        *,
        model_path: str | Path,
        prediction_dir: str | Path,
    ) -> list[dict[str, Any]]:
        """Predict with an explicit checkpoint in an isolated work directory."""

        self._validate_layout(training=False)
        self._validate_python()
        selected_model = Path(model_path).resolve()
        selected_prediction_dir = Path(prediction_dir).resolve()
        if not selected_model.is_file():
            raise FileNotFoundError(f"尚未找到 CGCNN 模型: {selected_model}")

        paths = [Path(path).resolve() for path in cif_paths]
        if not paths:
            return []
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"待预测 CIF 不存在: {', '.join(missing)}")

        self._prepare_prediction_dataset(paths, selected_prediction_dir)
        command = [
            str(self.python_executable), str(self.cgcnn_dir / "predict-r.py"),
            "--workers", "0", "--disable-cuda",
            str(selected_model), str(selected_prediction_dir),
        ]
        self._run(command, selected_prediction_dir)
        result_csv = selected_prediction_dir / "test_results.csv"
        if not result_csv.is_file():
            raise RuntimeError("预测结束，但没有生成 test_results.csv。")

        predictions = []
        with result_csv.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                predictions.append({
                    "cif_id": row["CIF_ID"],
                    "formation_energy_per_atom": float(row["Prediction"]),
                    "unit": "eV/atom",
                    "model_path": str(selected_model),
                })
        return predictions

    @staticmethod
    def _regression_metrics(result_csv: Path) -> dict[str, float]:
        targets, predictions = [], []
        if not result_csv.is_file():
            return {}
        with result_csv.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                targets.append(float(row["Target"]))
                predictions.append(float(row["Prediction"]))
        if not targets:
            return {}
        errors = [prediction - target for target, prediction in zip(targets, predictions)]
        mae = sum(abs(error) for error in errors) / len(errors)
        rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
        mean_target = sum(targets) / len(targets)
        denominator = sum((target - mean_target) ** 2 for target in targets)
        r2 = 1.0 - sum(error * error for error in errors) / denominator if denominator else float("nan")
        return {"mae": mae, "rmse": rmse, "r2": r2, "samples": len(targets)}

    def _promote(self, run_dir: Path, metadata: dict[str, Any]) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        for name in ("model_best.pth.tar", "checkpoint.pth.tar", "test_results.csv"):
            source = run_dir / name
            if source.is_file():
                shutil.copy2(source, self.artifact_dir / name)
        production_metadata = dict(metadata)
        production_metadata["model_path"] = str(self.model_path.resolve())
        self.metadata_path.write_text(
            json.dumps(production_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _prepare_prediction_dataset(
        self,
        cif_paths: list[Path],
        prediction_dir: Path,
    ) -> None:
        prediction_dir.mkdir(parents=True, exist_ok=True)
        for old_cif in prediction_dir.glob("*.cif"):
            old_cif.unlink()
        shutil.copy2(self.dataset_dir / "atom_init.json", prediction_dir / "atom_init.json")
        rows = []
        for index, source in enumerate(cif_paths, 1):
            cif_id = f"agent_candidate_{index:04d}"
            shutil.copy2(source, prediction_dir / f"{cif_id}.cif")
            rows.append((cif_id, 0.0))
        with (prediction_dir / "id_prop.csv").open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(rows)

    def _configured_python(self) -> str | None:
        config = self.project_root / ".cgcnn-python"
        return config.read_text(encoding="utf-8").strip() if config.is_file() else None

    def _validate_layout(self, training: bool) -> None:
        required = [
            self.cgcnn_dir / "predict-r.py", self.cgcnn_dir / "cgcnn" / "data.py",
            self.dataset_dir / "atom_init.json",
        ]
        if training:
            required.append(self.cgcnn_dir / "main-r.py")
            required.extend(self.dataset_dir / name for name in ("train.csv", "val.csv", "test.csv"))
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError(f"CGCNN 所需文件缺失: {', '.join(missing)}")

    def _validate_python(self) -> None:
        if not self.python_executable.is_file():
            raise FileNotFoundError(f"CGCNN Python 不存在: {self.python_executable}")
        check = subprocess.run(
            [str(self.python_executable), "-c", "import torch, numpy, sklearn, pymatgen"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=self._subprocess_env(),
        )
        if check.returncode:
            raise RuntimeError(f"CGCNN Python 环境缺少依赖:\n{check.stderr.strip()}")

    def _run_stream(self, command: list[str], cwd: Path, callback: LogCallback | None) -> str:
        process = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=self._subprocess_env(),
        )
        lines = []
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            lines.append(line)
            self._emit(callback, line)
        return_code = process.wait()
        output = "\n".join(lines)
        if return_code:
            raise RuntimeError(f"CGCNN 训练失败，退出码 {return_code}:\n{output[-4000:]}")
        return output

    def _run(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=self._subprocess_env(),
        )
        if completed.returncode:
            raise RuntimeError(
                f"CGCNN 命令运行失败。\nstdout:\n{completed.stdout[-4000:]}\n"
                f"stderr:\n{completed.stderr[-4000:]}"
            )
        return completed

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.site_packages.is_dir():
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(self.site_packages) + (os.pathsep + existing if existing else "")
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    @staticmethod
    def _emit(callback: LogCallback | None, line: str) -> None:
        if callback:
            callback(line)
