from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=12000)


class TaskCreatedResponse(BaseModel):
    task_id: str
    status: str
    status_url: str


class TaskStatusResponse(BaseModel):
    task_id: str
    question: str
    status: str
    stage: str
    stage_label: str
    stage_summary: str = ""
    progress: int
    waiting_for_human: bool = False
    review_type: str = ""
    review: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    workflow_timeline: list[dict[str, Any]] = Field(default_factory=list)
    stage_events: list[dict[str, Any]] = Field(default_factory=list)
    review_history: list[dict[str, Any]] = Field(default_factory=list)
    consultation_history: list[dict[str, Any]] = Field(default_factory=list)
    active_consultation: dict[str, Any] = Field(default_factory=dict)
    consultation_pending_continue: bool = False
    latest_report: dict[str, Any] = Field(default_factory=dict)


class ReviewSubmitRequest(BaseModel):
    review_id: str = Field(min_length=1, max_length=120)
    review_type: str = Field(min_length=1, max_length=120)
    decision: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=160)


class ReviewSubmittedResponse(BaseModel):
    task_id: str
    review_id: str
    status: str
    status_url: str


class TaskSummaryResponse(BaseModel):
    task_id: str
    question: str = ""
    status: str = "unknown"
    stage: str = ""
    stage_label: str = ""
    progress: int = 0
    waiting_for_human: bool = False
    review_type: str = ""
    created_at: str = ""
    updated_at: str = ""
    active_slurm_jobs: list[str] = Field(default_factory=list)


class TaskListResponse(BaseModel):
    tasks: list[TaskSummaryResponse] = Field(default_factory=list)


class TaskResumeResponse(BaseModel):
    task_id: str
    status: str
    target: str
    message: str
    status_url: str


class HealthResponse(BaseModel):
    status: str
    agent_available: bool
    llm_enabled: bool
    llm_configured: bool
    cluster_configured: bool
    remote_write_enabled: bool
    submission_enabled: bool


class ConnectionState(BaseModel):
    configured: bool
    status: str
    label: str
    detail: str


class RemoteOperationState(BaseModel):
    web_enabled: bool
    upload_enabled: bool
    submission_enabled: bool


class ConnectionStatusResponse(BaseModel):
    checked_at: str
    kimi: ConnectionState
    cluster: ConnectionState
    remote_operations: RemoteOperationState


class LiteratureTranslationRequest(BaseModel):
    doi: str = Field(default="", max_length=500)
    title: str = Field(default="", max_length=2000)
    abstract: str = Field(default="", max_length=12000)


class LiteratureTranslationResponse(BaseModel):
    title_en: str = ""
    title_zh: str = ""
    abstract_en: str = ""
    abstract_zh: str = ""
    translation_status: str
    translation_source: str
    translation_cached: bool = False
    translation_error: str = ""


class CGCNNTrainingRequest(BaseModel):
    epochs: int = Field(default=30, ge=1, le=200)
    batch_size: int = Field(default=32, ge=1, le=256)
    learning_rate: float = Field(default=0.001, gt=0, le=0.1)


class ConsultationRequest(BaseModel):
    question: str = Field(min_length=1, max_length=12000)
    task_id: str = Field(default="", max_length=160)


class ConsultationContinueRequest(BaseModel):
    consultation_id: str = Field(min_length=1, max_length=160)
