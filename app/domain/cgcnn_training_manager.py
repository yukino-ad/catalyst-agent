from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.cgcnn_service import CGCNNService


TERMINAL_STATUSES = {"completed", "failed"}


class CGCNNTrainingManager:
    """Run optional task-scoped CGCNN training without promoting the model."""

    def __init__(
        self,
        project_root: str | Path | None = None,
        service: CGCNNService | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.project_root = Path(
            project_root or Path(__file__).resolve().parents[2]
        ).resolve()
        self.root = self.project_root / "data" / "model_training_runs"
        self.service = service or CGCNNService(project_root=self.project_root)
        self.executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="cgcnn-training",
        )
        self._lock = threading.RLock()

    def start(
        self,
        task_id: str,
        structures: list[dict[str, Any]],
        *,
        epochs: int = 30,
        batch_size: int = 32,
        learning_rate: float = 0.001,
    ) -> dict[str, Any]:
        safe_task_id = self._identifier(task_id, "task_id")
        self._validate_parameters(epochs, batch_size, learning_rate)
        paths = self._structure_paths(structures)
        with self._lock:
            active = self.latest(safe_task_id)
            if active and active.get("status") not in TERMINAL_STATUSES:
                raise RuntimeError("该任务已有一个 CGCNN 临时训练正在运行。")
            run_id = f"cgcnn-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
            run_dir = self._run_dir(safe_task_id, run_id)
            run_dir.mkdir(parents=True, exist_ok=False)
            config = {
                "epochs": epochs,
                "batch_size": batch_size,
                "learning_rate": learning_rate,
                "optimizer": "Adam",
                "workers": 0,
                "seed": 123,
                "unit": "eV/atom",
                "prediction_structure_count": len(paths),
            }
            self._write_json(run_dir / "training_config.json", config)
            status = self._status(
                safe_task_id,
                run_id,
                "queued",
                "训练任务已进入后台队列。",
                config=config,
            )
            self._write_json(run_dir / "status.json", status)
            self.executor.submit(
                self._run,
                safe_task_id,
                run_id,
                paths,
                config,
            )
            return status

    def latest(self, task_id: str) -> dict[str, Any] | None:
        safe_task_id = self._identifier(task_id, "task_id")
        task_dir = self.root / safe_task_id
        if not task_dir.is_dir():
            return None
        values = [
            self.get(safe_task_id, path.name)
            for path in task_dir.iterdir()
            if path.is_dir() and (path / "status.json").is_file()
        ]
        return max(values, key=lambda item: str(item.get("created_at", "")), default=None)

    def get(self, task_id: str, run_id: str) -> dict[str, Any]:
        path = self._run_dir(
            self._identifier(task_id, "task_id"),
            self._identifier(run_id, "run_id"),
        ) / "status.json"
        if not path.is_file():
            raise FileNotFoundError("CGCNN 临时训练记录不存在。")
        return json.loads(path.read_text(encoding="utf-8"))

    def logs(self, task_id: str, run_id: str, tail: int = 400) -> dict[str, Any]:
        run_dir = self._run_dir(
            self._identifier(task_id, "task_id"),
            self._identifier(run_id, "run_id"),
        )
        if not (run_dir / "status.json").is_file():
            raise FileNotFoundError("CGCNN 临时训练记录不存在。")
        log_path = run_dir / "training.log"
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines() if log_path.is_file() else []
        return {
            "run_id": run_id,
            "content": "\n".join(lines[-max(1, min(tail, 2000)):]),
            "line_count": len(lines),
        }

    def predictions(self, task_id: str, run_id: str) -> list[dict[str, Any]]:
        path = self._run_dir(
            self._identifier(task_id, "task_id"),
            self._identifier(run_id, "run_id"),
        ) / "predictions.json"
        if not path.is_file():
            return []
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []

    def _run(
        self,
        task_id: str,
        run_id: str,
        structures: list[tuple[str, Path]],
        config: dict[str, Any],
    ) -> None:
        run_dir = self._run_dir(task_id, run_id)
        try:
            self._update(run_dir, "validating_dataset", "正在校验训练集、验证集和测试集。")
            report = self._validate_dataset(self.service.dataset_dir)
            self._write_json(run_dir / "dataset_report.json", report)
            self._append_log(run_dir, f"数据集校验完成: {json.dumps(report['split_sizes'], ensure_ascii=False)}")
            self._update(run_dir, "running", "CGCNN 正在训练。")
            experiment_name = f"task-{task_id}-{run_id}"
            metadata = self.service.train(
                epochs=int(config["epochs"]),
                batch_size=int(config["batch_size"]),
                learning_rate=float(config["learning_rate"]),
                experiment_name=experiment_name,
                log_callback=lambda line: self._append_log(run_dir, line),
                promote_if_better=False,
            )
            source_model = Path(str(metadata["model_path"])).resolve()
            task_model = run_dir / "model_best.pth.tar"
            shutil.copy2(source_model, task_model)
            prediction_dir = run_dir / "prediction_work"
            raw_predictions = self.service.predict_with_model(
                [path for _, path in structures],
                model_path=task_model,
                prediction_dir=prediction_dir,
            )
            predictions = [
                {
                    "structure_id": structure_id,
                    "formation_energy_ev_per_atom": prediction["formation_energy_per_atom"],
                    "unit": prediction.get("unit", "eV/atom"),
                    "source": "temporary_trained",
                    "temporary_model_run_id": run_id,
                }
                for (structure_id, _), prediction in zip(structures, raw_predictions)
            ]
            metrics = metadata.get("metrics", {})
            self._write_json(run_dir / "metrics.json", metrics)
            self._write_json(run_dir / "predictions.json", predictions)
            self._write_json(run_dir / "training_metadata.json", {
                **metadata,
                "model_path": "model_best.pth.tar",
                "production_model_replaced": False,
            })
            self._update(
                run_dir,
                "completed",
                "临时模型训练与候选结构预测完成。",
                metrics=metrics,
                prediction_count=len(predictions),
                completed_at=self._now(),
            )
        except Exception as error:
            self._append_log(run_dir, f"ERROR: {type(error).__name__}: {error}")
            self._update(
                run_dir,
                "failed",
                "CGCNN 临时训练失败。",
                error=f"{type(error).__name__}: {error}",
                completed_at=self._now(),
            )

    def _validate_dataset(self, dataset_dir: Path) -> dict[str, Any]:
        split_ids: dict[str, set[str]] = {}
        labels: list[float] = []
        missing: list[str] = []
        digest = hashlib.sha256()
        for split in ("train", "val", "test"):
            path = dataset_dir / f"{split}.csv"
            rows: set[str] = set()
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.reader(handle):
                    if len(row) < 2:
                        raise ValueError(f"{path.name} 存在不完整行。")
                    cif_name = str(row[0]).strip()
                    label = float(row[1])
                    if not math.isfinite(label):
                        raise ValueError(f"{path.name} 存在非有限标签: {cif_name}")
                    if cif_name in rows:
                        raise ValueError(f"{path.name} 存在重复 CIF: {cif_name}")
                    rows.add(cif_name)
                    labels.append(label)
                    if not (dataset_dir / cif_name).is_file():
                        missing.append(cif_name)
            split_ids[split] = rows
            digest.update(path.read_bytes())
        overlap = (split_ids["train"] & split_ids["val"]) | (
            split_ids["train"] & split_ids["test"]
        ) | (split_ids["val"] & split_ids["test"])
        if overlap:
            raise ValueError(f"数据集划分存在重复 CIF: {sorted(overlap)[:10]}")
        if missing:
            raise FileNotFoundError(f"CSV 引用的 CIF 缺失: {missing[:10]}")
        all_cifs = {path.name for path in dataset_dir.glob("*.cif")}
        assigned = set().union(*split_ids.values())
        return {
            "dataset_name": dataset_dir.name,
            "dataset_sha256": digest.hexdigest(),
            "split_sizes": {key: len(value) for key, value in split_ids.items()},
            "assigned_cif_count": len(assigned),
            "unassigned_cif_count": len(all_cifs - assigned),
            "unassigned_cifs": sorted(all_cifs - assigned),
            "label_unit": "eV/atom",
            "label_min": min(labels),
            "label_max": max(labels),
        }

    def _update(self, run_dir: Path, status: str, message: str, **extra: Any) -> None:
        path = run_dir / "status.json"
        current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        self._write_json(path, {
            **current,
            "status": status,
            "message": message,
            "updated_at": self._now(),
            **extra,
        })

    def _append_log(self, run_dir: Path, line: str) -> None:
        with self._lock, (run_dir / "training.log").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(str(line).rstrip("\r\n") + "\n")

    def _status(
        self,
        task_id: str,
        run_id: str,
        status: str,
        message: str,
        *,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        now = self._now()
        return {
            "schema_version": "c6-cgcnn-training-v1",
            "task_id": task_id,
            "run_id": run_id,
            "status": status,
            "message": message,
            "config": config,
            "temporary_model": True,
            "production_model_replaced": False,
            "created_at": now,
            "updated_at": now,
        }

    @staticmethod
    def _validate_parameters(epochs: int, batch_size: int, learning_rate: float) -> None:
        if not 1 <= epochs <= 200:
            raise ValueError("epochs 必须在 1 到 200 之间。")
        if not 1 <= batch_size <= 256:
            raise ValueError("batch_size 必须在 1 到 256 之间。")
        if not 0 < learning_rate <= 0.1:
            raise ValueError("learning_rate 必须大于 0 且不超过 0.1。")

    @staticmethod
    def _structure_paths(structures: list[dict[str, Any]]) -> list[tuple[str, Path]]:
        result: list[tuple[str, Path]] = []
        for item in structures:
            if not isinstance(item, dict):
                continue
            structure_id = str(item.get("structure_id", "")).strip()
            path = Path(str(item.get("cif_path", ""))).resolve()
            if structure_id and path.is_file():
                result.append((structure_id, path))
        if not result:
            raise ValueError("该任务没有可供临时模型预测的 C5 CIF 结构。")
        return result

    def _run_dir(self, task_id: str, run_id: str) -> Path:
        path = (self.root / task_id / run_id).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("训练记录路径越界。")
        return path

    @staticmethod
    def _identifier(value: str, name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in normalized):
            raise ValueError(f"{name} 格式无效。")
        return normalized

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
