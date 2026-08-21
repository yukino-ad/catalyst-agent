from __future__ import annotations

import argparse
import json
import mimetypes
import queue
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from app.legacy.agent import CatalystAgent
from tools.cgcnn_service import CGCNNService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"
DOWNLOAD_ROOTS = {
    "data": PROJECT_ROOT / "data",
    "model": PROJECT_ROOT / "models" / "formation-energy-cgcnn",
}


@dataclass
class TaskState:
    task_id: str
    question: str
    status: str = "queued"
    phase: str = "等待启动"
    progress: float = 0.0
    result: dict | None = None
    training: dict | None = None
    error: str | None = None
    raw_result: dict | None = None
    options: dict = field(default_factory=dict)
    selected_indices: list[int] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, event: str, data: object) -> None:
        with self.condition:
            self.events.append({"event": event, "data": data, "index": len(self.events)})
            self.condition.notify_all()


TASKS: dict[str, TaskState] = {}
TASKS_LOCK = threading.Lock()


def file_url(path: str | None) -> str | None:
    if not path:
        return None
    resolved = Path(path).resolve()
    for prefix, root in DOWNLOAD_ROOTS.items():
        try:
            relative = resolved.relative_to(root.resolve())
            return f"/files/{prefix}/" + quote(str(relative).replace("\\", "/"))
        except ValueError:
            continue
    return None


def serialize_result(result: dict) -> dict:
    structures = []
    for item in result.get("structures", []):
        screening = item.get("stability_screening") or {}
        structures.append(
            {
                "rank": item.get("candidate_rank"),
                "candidate": item.get("candidate_formula"),
                "formula": item.get("formula"),
                "formation_energy": item.get("formation_energy_per_atom"),
                "unit": item.get("formation_energy_unit", "eV/atom"),
                "screening": screening,
                "cif_url": file_url(item.get("cif_path")),
                "poscar_url": file_url(item.get("poscar_path")),
            }
        )
    postprocess = result.get("postprocess_result") or {"screening": [], "slabs": []}
    slabs = [
        {
            "atom_count": slab.get("atom_count"),
            "vacuum": slab.get("vacuum_angstrom"),
            "cif_url": file_url(slab.get("cif_path")),
            "poscar_url": file_url(slab.get("poscar_path")),
        }
        for slab in postprocess.get("slabs", [])
    ]
    metrics = CGCNNService().production_metrics()
    return {
        "question": result["plan"]["question"],
        "reaction": result["plan"]["reaction"],
        "product": result["plan"]["product"],
        "candidates": result.get("selected_candidates", []),
        "structures": structures,
        "slabs": slabs,
        "screening_passed": sum(bool(row.get("passed")) for row in postprocess.get("screening", [])),
        "screening_total": len(postprocess.get("screening", [])),
        "production_metrics": metrics,
        "ovito": result.get("ovito_result"),
        "warnings": [
            warning
            for warning in (result.get("cgcnn_error"), result.get("postprocess_error"), result.get("ovito_error"))
            if warning
        ],
    }


def finish_after_selection(state: TaskState) -> None:
    try:
        state.status = "postprocessing"
        state.phase = "稳定性判据与 (111) 切面"
        state.progress = 35
        state.emit("phase", {"name": state.phase, "progress": state.progress})
        structures = (state.raw_result or {}).get("structures", [])
        selected = [structures[index] for index in state.selected_indices]
        if not selected:
            raise ValueError("请至少选择一个结构。")
        agent = CatalystAgent()
        postprocess = agent.postprocess.screen_and_cleave(
            [item["cif_path"] for item in selected],
            [item["poscar_path"] for item in selected],
        )
        screening_by_path = {row["cif_path"]: row for row in postprocess["screening"]}
        for item in selected:
            item["stability_screening"] = screening_by_path.get(str(Path(item["cif_path"]).resolve()))
        state.raw_result["postprocess_result"] = postprocess
        state.result = serialize_result(state.raw_result)
        state.emit("postprocess", state.result)

        if state.options.get("train_model"):
            state.phase = "CGCNN 后台训练"
            state.emit("phase", {"name": state.phase, "progress": 55})
            epochs = state.options["epochs"]

            def log_callback(line: str) -> None:
                state.emit("log", line)
                if "Epoch:" in line:
                    try:
                        epoch = int(line.split("Epoch: [", 1)[1].split("]", 1)[0]) + 1
                        state.progress = min(98, 55 + epoch / epochs * 43)
                        state.emit("progress", state.progress)
                    except (IndexError, ValueError):
                        pass

            state.training = agent.cgcnn.train(epochs=epochs, log_callback=log_callback)
            state.emit("training", state.training)

        state.status = "completed"
        state.phase = "任务完成"
        state.progress = 100
        state.emit("done", {"status": state.status, "progress": 100})
    except Exception as error:
        state.status = "failed"
        state.phase = "任务失败"
        state.error = str(error)
        state.emit("error", state.error)


def run_task(state: TaskState, options: dict) -> None:
    try:
        state.status = "running"
        state.phase = "生成候选与结构"
        state.emit("phase", {"name": state.phase, "progress": 6})
        agent = CatalystAgent()
        result = agent.run(
            state.question,
            candidate_count=options["candidate_count"],
            build_params={
                "structures_per_candidate": options["structures_per_candidate"],
                "seed": options["seed"],
            },
            predict_properties=True,
            open_ovito=options["open_ovito"],
            run_postprocess=False,
        )
        state.raw_result = result
        state.options = options
        state.result = serialize_result(result)
        state.phase = "等待选择结构"
        state.status = "awaiting_selection"
        state.progress = 30
        state.emit("result", state.result)
        state.emit("phase", {"name": state.phase, "progress": state.progress})
    except Exception as error:
        state.status = "failed"
        state.phase = "任务失败"
        state.error = str(error)
        state.emit("error", state.error)


class WebHandler(BaseHTTPRequestHandler):
    server_version = "CatalystAgentWeb/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._serve_static(WEB_ROOT / "index.html")
        if parsed.path.startswith("/static/"):
            return self._serve_static(WEB_ROOT / parsed.path.removeprefix("/static/"))
        if parsed.path.startswith("/files/"):
            return self._serve_download(parsed.path.removeprefix("/files/"))
        if parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/events"):
            task_id = parsed.path.split("/")[3]
            return self._stream_events(task_id, parse_qs(parsed.query))
        if parsed.path.startswith("/api/tasks/"):
            task_id = parsed.path.rsplit("/", 1)[-1]
            return self._task_status(task_id)
        if parsed.path == "/api/health":
            return self._json({"status": "ok"})
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/confirm"):
            return self._confirm_selection(parsed.path.split("/")[3])
        if parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/ovito"):
            return self._open_ovito(parsed.path.split("/")[3])
        if parsed.path != "/api/tasks":
            return self.send_error(HTTPStatus.NOT_FOUND)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            question = str(payload.get("question", "")).strip()
            if not question:
                raise ValueError("请输入科研问题。")
            candidate_count = int(payload.get("candidate_count", 1))
            structures_per_candidate = int(payload.get("structures_per_candidate", 1))
            epochs = int(payload.get("epochs", 60))
            if not 1 <= candidate_count <= 3 or not 1 <= structures_per_candidate <= 3:
                raise ValueError("候选数量和每候选排布数必须在 1-3 之间。")
            if not 1 <= epochs <= 500:
                raise ValueError("训练轮数必须在 1-500 之间。")
            options = {
                "candidate_count": candidate_count,
                "structures_per_candidate": structures_per_candidate,
                "epochs": epochs,
                "seed": int(payload.get("seed", 42)),
                "train_model": bool(payload.get("train_model", False)),
                "open_ovito": bool(payload.get("open_ovito", False)),
            }
            task_id = uuid.uuid4().hex
            state = TaskState(task_id=task_id, question=question)
            with TASKS_LOCK:
                TASKS[task_id] = state
            threading.Thread(target=run_task, args=(state, options), daemon=True).start()
            self._json({"task_id": task_id}, status=HTTPStatus.ACCEPTED)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

    def _confirm_selection(self, task_id: str) -> None:
        state = TASKS.get(task_id)
        if not state:
            return self.send_error(HTTPStatus.NOT_FOUND)
        if state.status != "awaiting_selection":
            return self._json({"error": "任务当前不处于待选择状态。"}, HTTPStatus.CONFLICT)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            indices = sorted(set(int(index) for index in payload.get("indices", [])))
            count = len((state.raw_result or {}).get("structures", []))
            if not indices or any(index < 0 or index >= count for index in indices):
                raise ValueError("请选择有效结构。")
            state.selected_indices = indices
            threading.Thread(target=finish_after_selection, args=(state,), daemon=True).start()
            self._json({"accepted": True}, HTTPStatus.ACCEPTED)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _open_ovito(self, task_id: str) -> None:
        state = TASKS.get(task_id)
        if not state:
            return self.send_error(HTTPStatus.NOT_FOUND)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            slab_index = int(payload.get("slab_index", 0))
            slabs = ((state.raw_result or {}).get("postprocess_result") or {}).get("slabs", [])
            if not 0 <= slab_index < len(slabs):
                raise ValueError("Slab 不存在。")
            result = CatalystAgent().ovito.open_structures([slabs[slab_index]["poscar_path"]])
            self._json({"opened": result, "view": payload.get("view", "main")})
        except (ValueError, OSError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _task_status(self, task_id: str) -> None:
        state = TASKS.get(task_id)
        if not state:
            return self.send_error(HTTPStatus.NOT_FOUND)
        self._json(
            {
                "task_id": state.task_id,
                "question": state.question,
                "status": state.status,
                "phase": state.phase,
                "progress": state.progress,
                "result": state.result,
                "training": state.training,
                "error": state.error,
            }
        )

    def _stream_events(self, task_id: str, query: dict) -> None:
        state = TASKS.get(task_id)
        if not state:
            return self.send_error(HTTPStatus.NOT_FOUND)
        cursor = int(query.get("cursor", ["0"])[0])
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                with state.condition:
                    if cursor >= len(state.events) and state.status not in {"completed", "failed"}:
                        state.condition.wait(timeout=10)
                    events = state.events[cursor:]
                for item in events:
                    payload = json.dumps(item["data"], ensure_ascii=False)
                    message = f"id: {item['index']}\nevent: {item['event']}\ndata: {payload}\n\n"
                    self.wfile.write(message.encode("utf-8"))
                    self.wfile.flush()
                    cursor = item["index"] + 1
                if state.status in {"completed", "failed"} and cursor >= len(state.events):
                    break
                if not events:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _serve_static(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            resolved.relative_to(WEB_ROOT.resolve())
            data = resolved.read_bytes()
        except (ValueError, OSError):
            return self.send_error(HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(resolved.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_download(self, relative_text: str) -> None:
        parts = unquote(relative_text).split("/", 1)
        if len(parts) != 2 or parts[0] not in DOWNLOAD_ROOTS:
            return self.send_error(HTTPStatus.NOT_FOUND)
        root = DOWNLOAD_ROOTS[parts[0]]
        relative = Path(parts[1])
        for root in (root,):
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                continue
            if candidate.is_file():
                return self._serve_file(candidate)
        self.send_error(HTTPStatus.NOT_FOUND)

    def _serve_file(self, path: Path) -> None:
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Catalyst Agent web application")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), WebHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Catalyst Agent Web: {url}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
