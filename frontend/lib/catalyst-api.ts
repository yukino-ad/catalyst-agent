const API_BASE_URL =
  process.env.CATALYST_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export type CatalystTask = {
  task_id: string;
  question: string;
  status:
    | "queued"
    | "running"
    | "resuming"
    | "paused_for_consultation"
    | "waiting_for_human"
    | "completed"
    | "failed";
  stage: string;
  stage_label: string;
  stage_summary: string;
  progress: number;
  waiting_for_human: boolean;
  review_type: string;
  review: Record<string, unknown>;
  message: string;
  error: string;
  created_at: string;
  updated_at: string;
  workflow_timeline: WorkflowStage[];
  stage_events: StageEvent[];
  review_history: ReviewHistoryItem[];
  consultation_history: ConsultationRecord[];
  active_consultation: ConsultationRecord | Record<string, never>;
  consultation_pending_continue: boolean;
  latest_report: TaskReportMetadata | Record<string, never>;
};

export type TaskReportMetadata = {
  task_id: string;
  generated_at: string;
  status: "ready";
  formats: Array<"html" | "md" | "json">;
};

export type ConsultationIntent =
  | "workflow_command"
  | "vasp_consultation"
  | "scientific_explanation"
  | "report_request"
  | "general_research_chat";

export type ConsultationRecord = {
  consultation_id: string;
  task_id: string;
  intent: ConsultationIntent;
  question: string;
  answer: string;
  answer_source: "kimi" | "local_rules" | "local_fallback";
  paused_stage: string;
  requires_continue_confirmation: boolean;
  continued: boolean;
  created_at: string;
  continued_at?: string;
  report?: TaskReportMetadata;
  answer_recovery_note?: string;
};

export type ConsultationResponse =
  | (ConsultationRecord & { create_workflow: false })
  | {
      intent: ConsultationIntent;
      answer: string;
      create_workflow: true;
      requires_continue_confirmation: false;
    };

export type CatalystTaskSummary = {
  task_id: string;
  question: string;
  status: string;
  stage: string;
  stage_label: string;
  progress: number;
  waiting_for_human: boolean;
  review_type: string;
  created_at: string;
  updated_at: string;
  active_slurm_jobs: string[];
};

export type CatalystFile = {
  file_id: string;
  name: string;
  label: string;
  suffix: string;
  category: string;
  size_bytes: number;
  previewable: boolean;
  downloadable: boolean;
  structure: boolean;
};

export type CatalystStructure = {
  structure_id: string;
  name: string;
  label: string;
  category: string;
};

export type StructureData = {
  structure_id: string;
  name: string;
  lattice: number[][];
  atoms: Array<{ index: number; element: string; position: number[]; movable: boolean }>;
  atom_count: number;
  elements: string[];
};

export type CatalystJob = {
  slurm_job_id: string;
  task_id: string;
  job_id: string;
  job_source: string;
  scheduler_state: string;
  scheduler_elapsed?: string | null;
  scheduler_detail?: string | null;
  monitoring_status: string;
  terminal: boolean;
  last_polled_at?: string | null;
  vasp_decision: string;
  vasp_ionic_steps?: number | null;
  final_toten_ev?: number | null;
  max_force_ev_ang?: number | null;
  download_eligible: boolean;
};

export type CGCNNTraining = {
  task_id: string;
  run_id: string;
  status: "queued" | "validating_dataset" | "running" | "completed" | "failed";
  message: string;
  metrics?: Record<string, number>;
  prediction_count?: number;
  error?: string;
  production_model_replaced: boolean;
  created_at: string;
  updated_at: string;
};

export type StageEvent = {
  event_id: string;
  node_id: string;
  created_at: string;
  stage: WorkflowStage;
};

export type ReviewHistoryItem = {
  review_id: string;
  review_type: string;
  status: "waiting" | "submitted";
  review: Record<string, unknown>;
  decision: Record<string, unknown>;
  created_at: string;
  submitted_at: string;
};

export type WorkflowStage = {
  stage_id: string;
  stage_label: string;
  label: string;
  group: "A" | "B" | "C" | "C12";
  status: "pending" | "running" | "completed" | "waiting_review" | "skipped" | "blocked" | "failed";
  summary: string;
  outputs: Record<string, unknown>;
  progress: number;
  requires_human_action: boolean;
  started_at: string;
  completed_at: string;
  updated_at: string;
  next: string;
  next_stage: string;
  skip_reason: string;
  error: string;
};

export async function createCatalystTask(question: string) {
  const response = await fetch(`${API_BASE_URL}/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    cache: "no-store",
  });
  if (!response.ok) throw await apiError(response, "创建任务失败");
  return (await response.json()) as {
    task_id: string;
    status: string;
    status_url: string;
  };
}

export async function getCatalystTask(taskId: string): Promise<CatalystTask> {
  const baseUrl = typeof window === "undefined" ? API_BASE_URL : "";
  const response = await fetch(`${baseUrl}/api/tasks/${encodeURIComponent(taskId)}`, {
    cache: "no-store",
  });
  if (!response.ok) throw await apiError(response, "读取任务状态失败");
  return (await response.json()) as CatalystTask;
}

export async function listCatalystTasks(): Promise<CatalystTaskSummary[]> {
  const baseUrl = typeof window === "undefined" ? API_BASE_URL : "";
  const response = await fetch(`${baseUrl}/api/tasks`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取历史任务失败");
  const payload = (await response.json()) as { tasks: CatalystTaskSummary[] };
  return payload.tasks;
}

export async function resumeCatalystTask(taskId: string) {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/resume`, {
    method: "POST",
  });
  if (!response.ok) throw await apiError(response, "恢复任务失败");
  return (await response.json()) as {
    task_id: string;
    status: string;
    target: string;
    message: string;
  };
}

export async function archiveCatalystTask(taskId: string) {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/archive`, {
    method: "POST",
  });
  if (!response.ok) throw await apiError(response, "归档任务失败");
  return response.json();
}

export async function listTaskFiles(taskId: string): Promise<CatalystFile[]> {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/files`, {
    cache: "no-store",
  });
  if (!response.ok) throw await apiError(response, "读取任务文件失败");
  return ((await response.json()) as { files: CatalystFile[] }).files;
}

export async function previewTaskFile(taskId: string, fileId: string) {
  const response = await fetch(
    `/api/tasks/${encodeURIComponent(taskId)}/files/${encodeURIComponent(fileId)}/preview`,
    { cache: "no-store" },
  );
  if (!response.ok) throw await apiError(response, "读取文件预览失败");
  return response.json() as Promise<{
    name: string;
    mode: string;
    content: string | string[];
    truncated: boolean;
  }>;
}

export async function listTaskStructures(taskId: string): Promise<CatalystStructure[]> {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/structures`, {
    cache: "no-store",
  });
  if (!response.ok) throw await apiError(response, "读取结构列表失败");
  return ((await response.json()) as { structures: CatalystStructure[] }).structures;
}

export async function getTaskStructure(
  taskId: string,
  structureId: string,
): Promise<StructureData> {
  const response = await fetch(
    `/api/tasks/${encodeURIComponent(taskId)}/structures/${encodeURIComponent(structureId)}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw await apiError(response, "读取三维结构失败");
  return response.json() as Promise<StructureData>;
}

export async function listTaskJobs(taskId: string): Promise<CatalystJob[]> {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/jobs`, {
    cache: "no-store",
  });
  if (!response.ok) throw await apiError(response, "读取 DFT 作业失败");
  return ((await response.json()) as { jobs: CatalystJob[] }).jobs;
}

export async function refreshTaskJob(jobId: string): Promise<CatalystJob> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/refresh`, {
    method: "POST",
  });
  if (!response.ok) throw await apiError(response, "刷新 Slurm 状态失败");
  return response.json() as Promise<CatalystJob>;
}

export async function getTaskJobLog(jobId: string, name: string) {
  const response = await fetch(
    `/api/jobs/${encodeURIComponent(jobId)}/logs?name=${encodeURIComponent(name)}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw await apiError(response, "读取远程日志失败");
  return response.json() as Promise<{ name: string; content: string; read_at: string }>;
}

export async function startCGCNNTraining(taskId: string): Promise<CGCNNTraining> {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/cgcnn-training`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ epochs: 30, batch_size: 32, learning_rate: 0.001 }),
  });
  if (!response.ok) throw await apiError(response, "启动 CGCNN 临时训练失败");
  return response.json() as Promise<CGCNNTraining>;
}

export async function getLatestCGCNNTraining(taskId: string): Promise<CGCNNTraining | null> {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/cgcnn-training`, {
    cache: "no-store",
  });
  if (!response.ok) throw await apiError(response, "读取 CGCNN 训练状态失败");
  return ((await response.json()) as { training: CGCNNTraining | null }).training;
}

export async function getCGCNNTraining(taskId: string, runId: string): Promise<CGCNNTraining> {
  const response = await fetch(
    `/api/tasks/${encodeURIComponent(taskId)}/cgcnn-training/${encodeURIComponent(runId)}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw await apiError(response, "读取 CGCNN 训练状态失败");
  return response.json() as Promise<CGCNNTraining>;
}

export async function getCGCNNTrainingLog(taskId: string, runId: string) {
  const response = await fetch(
    `/api/tasks/${encodeURIComponent(taskId)}/cgcnn-training/${encodeURIComponent(runId)}/logs?tail=400`,
    { cache: "no-store" },
  );
  if (!response.ok) throw await apiError(response, "读取 CGCNN 训练日志失败");
  return response.json() as Promise<{ run_id: string; content: string; line_count: number }>;
}

export async function askCatalystAssistant(question: string, taskId = "") {
  const baseUrl = typeof window === "undefined" ? API_BASE_URL : "";
  const response = await fetch(`${baseUrl}/api/conversations/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, task_id: taskId }),
    cache: "no-store",
  });
  if (!response.ok) throw await apiError(response, "科研咨询失败");
  return response.json() as Promise<ConsultationResponse>;
}

export async function streamCatalystAssistant(
  question: string,
  taskId: string,
  onDelta: (delta: string) => void,
) {
  const baseUrl = typeof window === "undefined" ? API_BASE_URL : "";
  const path =
    typeof window === "undefined"
      ? "/api/conversations/respond/stream"
      : "/api/conversations/respond?stream=1";
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, task_id: taskId }),
    cache: "no-store",
  });
  if (!response.ok || !response.body) throw await apiError(response, "科研咨询流式请求失败");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: ConsultationResponse | null = null;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : (lines.pop() ?? "");
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as {
        type: "delta" | "final" | "error";
        delta?: string;
        result?: ConsultationResponse;
        error?: string;
      };
      if (event.type === "delta" && event.delta) onDelta(event.delta);
      if (event.type === "final" && event.result) finalResult = event.result;
      if (event.type === "error") throw new Error(event.error || "科研咨询流式请求失败");
    }
    if (done) break;
  }
  if (!finalResult) throw new Error("Kimi 流结束时没有返回完整咨询记录。");
  return finalResult;
}

export async function continueConsultedWorkflow(taskId: string, consultationId: string) {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/consultations/continue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ consultation_id: consultationId }),
  });
  if (!response.ok) throw await apiError(response, "继续工作流失败");
  return response.json() as Promise<{ task_id: string; status: string; message: string }>;
}

export async function generateTaskReport(taskId: string): Promise<TaskReportMetadata> {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/report`, {
    method: "POST",
  });
  if (!response.ok) throw await apiError(response, "生成任务报告失败");
  return response.json() as Promise<TaskReportMetadata>;
}

async function apiError(response: Response, fallback: string) {
  let detail = "";
  try {
    const payload = (await response.json()) as { detail?: string };
    detail = payload.detail ?? "";
  } catch {
    detail = await response.text();
  }
  return new Error(`${fallback} (${response.status})${detail ? `：${detail}` : ""}`);
}
