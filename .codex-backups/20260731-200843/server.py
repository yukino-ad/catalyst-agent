from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from app.api.schemas import (
    CGCNNTrainingRequest,
    ConsultationContinueRequest,
    ConsultationRequest,
    ConnectionStatusResponse,
    HealthResponse,
    LiteratureTranslationRequest,
    LiteratureTranslationResponse,
    ReviewSubmittedResponse,
    ReviewSubmitRequest,
    TaskListResponse,
    TaskResumeResponse,
    TaskSummaryResponse,
    TaskCreatedResponse,
    TaskCreateRequest,
    TaskStatusResponse,
)
from app.api.task_manager import TaskManager
from app.api.job_monitor import JobMonitorFacade
from app.api.research_assets import ResearchAssetService
from app.domain.literature_translation import LiteratureTranslationService
from app.domain.cgcnn_training_manager import CGCNNTrainingManager
from app.domain.workflow_consultation import WorkflowConsultationService
from app.domain.task_report import TaskReportService
from app.api.connection_status import ConnectionStatusService, web_remote_operations_enabled


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

app = FastAPI(
    title="Catalyst Agent API",
    version="0.1.0-f2",
    docs_url="/docs",
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
task_manager = TaskManager()
research_assets = ResearchAssetService()
job_monitor = JobMonitorFacade()
literature_translation = LiteratureTranslationService()
cgcnn_training = CGCNNTrainingManager()
workflow_consultation = WorkflowConsultationService()
task_reports = TaskReportService()
connection_status = ConnectionStatusService()


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    llm_enabled = _truthy(os.getenv("LLM_ENABLED", "false"))
    return HealthResponse(
        status="ok",
        agent_available=True,
        llm_enabled=llm_enabled,
        llm_configured=bool(
            llm_enabled
            and os.getenv("LLM_API_KEY", "").strip()
            and os.getenv("LLM_BASE_URL", "").strip()
            and os.getenv("LLM_MODEL", "").strip()
        ),
        cluster_configured=bool(
            os.getenv("CLUSTER_SSH_HOST", "").strip()
            and os.getenv("CLUSTER_SSH_USER", "").strip()
            and os.getenv("CLUSTER_SSH_KEY_PATH", "").strip()
        ),
        remote_write_enabled=bool(
            web_remote_operations_enabled()
            and _truthy(os.getenv("CLUSTER_REMOTE_WRITE_ENABLED", "false"))
        ),
        submission_enabled=bool(
            web_remote_operations_enabled()
            and _truthy(os.getenv("CLUSTER_SUBMISSION_ENABLED", "false"))
        ),
    )


@app.get("/api/system/connections", response_model=ConnectionStatusResponse)
def get_connection_status() -> ConnectionStatusResponse:
    return ConnectionStatusResponse(**connection_status.configured_status())


@app.post("/api/system/connections/check", response_model=ConnectionStatusResponse)
def check_connections() -> ConnectionStatusResponse:
    return ConnectionStatusResponse(**connection_status.check())


@app.post(
    "/api/literature/translations",
    response_model=LiteratureTranslationResponse,
)
def translate_literature(
    request: LiteratureTranslationRequest,
) -> LiteratureTranslationResponse:
    result = literature_translation.translate(
        doi=request.doi,
        title=request.title,
        abstract=request.abstract,
    )
    return LiteratureTranslationResponse(**result)


@app.post("/api/conversations/respond")
def respond_to_conversation(request: ConsultationRequest) -> dict[str, Any]:
    try:
        result = workflow_consultation.respond(request.question, request.task_id.strip())
        task_id = request.task_id.strip()
        if result.get("intent") == "report_request" and task_id:
            report = task_reports.generate(task_id)
            consultation_id = str(result.get("consultation_id", ""))
            if consultation_id:
                result = workflow_consultation.attach_report(
                    task_id, consultation_id, report
                )
                result["create_workflow"] = False
        return result
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/conversations/respond/stream")
def stream_conversation(request: ConsultationRequest) -> StreamingResponse:
    def events():
        try:
            for event in workflow_consultation.respond_stream(
                request.question, request.task_id.strip()
            ):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except (FileNotFoundError, ValueError) as error:
            yield json.dumps(
                {"type": "error", "error": str(error)}, ensure_ascii=False
            ) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/tasks/{task_id}/consultations/continue")
def continue_after_consultation(
    task_id: str,
    request: ConsultationContinueRequest,
) -> dict[str, Any]:
    record = task_manager.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        updated = task_manager.continue_after_consultation(
            task_id, request.consultation_id
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "task_id": task_id,
        "status": updated.get("workflow_status", ""),
        "message": updated.get("message", ""),
    }


@app.post("/api/tasks", response_model=TaskCreatedResponse, status_code=202)
def create_task(request: TaskCreateRequest) -> TaskCreatedResponse:
    record = task_manager.create(request.question)
    task_id = str(record["task_id"])
    return TaskCreatedResponse(
        task_id=task_id,
        status="queued",
        status_url=f"/api/tasks/{task_id}",
    )


@app.get("/api/tasks", response_model=TaskListResponse)
def list_tasks(include_archived: bool = False) -> TaskListResponse:
    return TaskListResponse(tasks=[
        TaskSummaryResponse(
            task_id=str(item.get("task_id", "")),
            question=str(item.get("question", "")),
            status=str(item.get("workflow_status", "unknown")),
            stage=str(item.get("stage", "")),
            stage_label=str(item.get("stage_label", "")),
            progress=int(item.get("progress", 0) or 0),
            waiting_for_human=bool(item.get("waiting_for_human", False)),
            review_type=str(item.get("review_type", "")),
            created_at=str(item.get("created_at", "")),
            updated_at=str(item.get("updated_at", "")),
            active_slurm_jobs=[str(value) for value in item.get("active_slurm_jobs", [])],
        )
        for item in task_manager.list(include_archived=include_archived)
        if item.get("task_id")
    ])


@app.get("/api/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task(task_id: str) -> TaskStatusResponse:
    record = task_manager.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    consultation_history = [
        workflow_consultation.normalize_history_item(item)
        for item in record.get("consultation_history", [])
        if isinstance(item, dict)
    ]
    active_consultation = (
        workflow_consultation.normalize_history_item(record.get("active_consultation", {}))
        if isinstance(record.get("active_consultation", {}), dict)
        else {}
    )
    return TaskStatusResponse(
        task_id=str(record.get("task_id", task_id)),
        question=str(record.get("question", "")),
        status=str(record.get("workflow_status", "unknown")),
        stage=str(record.get("stage", "")),
        stage_label=str(record.get("stage_label", "")),
        stage_summary=str(record.get("stage_summary", "")),
        progress=int(record.get("progress", 0)),
        waiting_for_human=bool(record.get("waiting_for_human", False)),
        review_type=str(record.get("review_type", "")),
        review=record.get("review", {}) if isinstance(record.get("review"), dict) else {},
        message=str(record.get("message", "")),
        error=str(record.get("error", "")),
        created_at=str(record.get("created_at", "")),
        updated_at=str(record.get("updated_at", "")),
        workflow_timeline=record.get("workflow_timeline", []) if isinstance(record.get("workflow_timeline", []), list) else [],
        stage_events=record.get("stage_events", []) if isinstance(record.get("stage_events", []), list) else [],
        review_history=record.get("review_history", []) if isinstance(record.get("review_history", []), list) else [],
        consultation_history=consultation_history,
        active_consultation=active_consultation,
        consultation_pending_continue=bool(
            record.get("consultation_pending_continue", False)
        ),
        latest_report=(
            record.get("latest_report", {})
            if isinstance(record.get("latest_report", {}), dict)
            else {}
        ),
    )


@app.post("/api/tasks/{task_id}/report")
def generate_task_report(task_id: str) -> dict[str, Any]:
    try:
        return task_reports.generate(task_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/tasks/{task_id}/report")
def get_task_report(task_id: str) -> dict[str, Any]:
    if task_manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    report = task_reports.metadata(task_id)
    if not report:
        raise HTTPException(status_code=404, detail="Task report has not been generated.")
    return report


@app.get("/api/tasks/{task_id}/report/download")
def download_task_report(
    task_id: str,
    format: str = Query(default="html", pattern="^(html|md|json)$"),
) -> FileResponse:
    try:
        path = task_reports.path(task_id, format)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    media_types = {
        "html": "text/html; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "json": "application/json; charset=utf-8",
    }
    return FileResponse(path, filename=path.name, media_type=media_types[format])


@app.post("/api/tasks/{task_id}/resume", response_model=TaskResumeResponse)
def resume_task(task_id: str) -> TaskResumeResponse:
    try:
        result = task_manager.resume_plan(task_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return TaskResumeResponse(
        task_id=task_id,
        status=result["status"],
        target=result["target"],
        message=result["message"],
        status_url=f"/api/tasks/{task_id}",
    )


@app.post("/api/tasks/{task_id}/archive", response_model=TaskResumeResponse)
def archive_task(task_id: str) -> TaskResumeResponse:
    try:
        task_manager.archive(task_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return TaskResumeResponse(
        task_id=task_id,
        status="archived",
        target="archive",
        message="任务已归档，科研文件和审查记录仍保留。",
        status_url=f"/api/tasks/{task_id}",
    )


@app.get("/api/tasks/{task_id}/files")
def list_task_files(task_id: str) -> dict[str, Any]:
    try:
        return {"task_id": task_id, "files": research_assets.list_files(task_id)}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/tasks/{task_id}/files/{file_id}/preview")
def preview_task_file(task_id: str, file_id: str) -> dict[str, Any]:
    try:
        return research_assets.preview(task_id, file_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/tasks/{task_id}/files/{file_id}/download")
def download_task_file(task_id: str, file_id: str) -> FileResponse:
    try:
        path = research_assets.downloadable(task_id, file_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/api/tasks/{task_id}/structures")
def list_task_structures(task_id: str) -> dict[str, Any]:
    try:
        return {"task_id": task_id, "structures": research_assets.list_structures(task_id)}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/tasks/{task_id}/structures/{structure_id}")
def get_task_structure(task_id: str, structure_id: str) -> dict[str, Any]:
    try:
        return research_assets.structure(task_id, structure_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/tasks/{task_id}/cgcnn-training", status_code=202)
def start_cgcnn_training(
    task_id: str,
    request: CGCNNTrainingRequest,
) -> dict[str, Any]:
    try:
        structures = task_manager.formation_energy_structures(task_id)
        return cgcnn_training.start(
            task_id,
            structures,
            epochs=request.epochs,
            batch_size=request.batch_size,
            learning_rate=request.learning_rate,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/tasks/{task_id}/cgcnn-training")
def get_latest_cgcnn_training(task_id: str) -> dict[str, Any]:
    if task_manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"training": cgcnn_training.latest(task_id)}


@app.get("/api/tasks/{task_id}/cgcnn-training/{run_id}")
def get_cgcnn_training(task_id: str, run_id: str) -> dict[str, Any]:
    try:
        return cgcnn_training.get(task_id, run_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/tasks/{task_id}/cgcnn-training/{run_id}/logs")
def get_cgcnn_training_logs(
    task_id: str,
    run_id: str,
    tail: int = Query(default=400, ge=1, le=2000),
) -> dict[str, Any]:
    try:
        return cgcnn_training.logs(task_id, run_id, tail)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/tasks/{task_id}/jobs")
def list_task_jobs(task_id: str) -> dict[str, Any]:
    if task_manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "jobs": job_monitor.list_for_task(task_id)}


@app.get("/api/jobs/{slurm_job_id}")
def get_job(slurm_job_id: str) -> dict[str, Any]:
    try:
        return job_monitor.get(slurm_job_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/jobs/{slurm_job_id}/refresh")
def refresh_job(slurm_job_id: str) -> dict[str, Any]:
    try:
        return job_monitor.refresh(slurm_job_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/jobs/{slurm_job_id}/logs")
def get_job_logs(
    slurm_job_id: str,
    name: str = Query(default="OUTCAR", max_length=80),
) -> dict[str, Any]:
    try:
        return job_monitor.logs(slurm_job_id, name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post(
    "/api/tasks/{task_id}/reviews",
    response_model=ReviewSubmittedResponse,
    status_code=202,
)
def submit_review(
    task_id: str,
    request: ReviewSubmitRequest,
) -> ReviewSubmittedResponse:
    try:
        record = task_manager.submit_review(
            task_id=task_id,
            review_id=request.review_id,
            review_type=request.review_type,
            decision=request.decision,
            idempotency_key=request.idempotency_key,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ReviewSubmittedResponse(
        task_id=task_id,
        review_id=request.review_id,
        status=str(record.get("workflow_status", "resuming")),
        status_url=f"/api/tasks/{task_id}",
    )


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
