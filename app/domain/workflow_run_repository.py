from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _path_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


class WorkflowRunRepository:
    """Small durable index joining main-graph tasks to asynchronous jobs."""

    def __init__(self, root: str | Path = "data/workflow_runs") -> None:
        self.root = Path(root)

    def update(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        path = self.root / f"{task_id}.json"
        with _path_lock(path):
            current = {}
            if path.is_file():
                current = json.loads(path.read_text(encoding="utf-8"))
            value = {
                **current,
                "schema_version": "c11.9",
                "task_id": task_id,
                **changes,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
            try:
                temporary.write_text(
                    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                self._replace_with_retry(temporary, path)
            finally:
                if temporary.exists():
                    try:
                        temporary.unlink()
                    except OSError:
                        pass
            return {**value, "record_path": str(path.resolve())}

    def get(self, task_id: str) -> dict[str, Any] | None:
        path = self.root / f"{task_id}.json"
        with _path_lock(path):
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

    def list_records(self, include_archived: bool = False) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in self.root.glob("*.json"):
            if path.name.startswith("."):
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            if value.get("archived") and not include_archived:
                continue
            records.append(value)
        records.sort(
            key=lambda item: str(item.get("updated_at", item.get("created_at", ""))),
            reverse=True,
        )
        return records

    def archive(self, task_id: str) -> dict[str, Any]:
        if self.get(task_id) is None:
            raise FileNotFoundError(f"Task not found: {task_id}")
        return self.update(task_id, {
            "archived": True,
            "archived_at": datetime.now(timezone.utc).isoformat(),
        })

    @staticmethod
    def _replace_with_retry(temporary: Path, destination: Path) -> None:
        delays = (0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.0)
        for attempt in range(len(delays) + 1):
            try:
                os.replace(temporary, destination)
                return
            except PermissionError:
                if attempt == len(delays):
                    raise
                time.sleep(delays[attempt])
