import type { UIMessage } from "ai";
import type { CatalystTask, ConsultationRecord, WorkflowStage } from "@/lib/catalyst-api";

export type ReviewItem = Record<string, unknown> & {
  evidence_id?: string;
  candidate_id?: string;
  structure_id?: string;
  structure_available?: boolean;
  title?: string;
  abstract?: string;
  doi?: string;
  assertions?: Array<Record<string, unknown> & { assertion_id?: string }>;
  file_previews?: Record<string, unknown>;
  pretrained_formation_energy_ev_per_atom?: number;
  temporary_formation_energy_ev_per_atom?: number;
  prediction_difference_ev_per_atom?: number;
};

export type LiteratureTranslation = {
  title_en: string;
  title_zh: string;
  abstract_en: string;
  abstract_zh: string;
  translation_status: string;
  translation_source: string;
  translation_cached: boolean;
  translation_error: string;
};

export type ReviewOption = {
  mode: string;
  label: string;
  label_zh?: string;
  explanation?: string;
  explanation_zh?: string;
  runs?: string[];
  disabled?: boolean;
};

export type ReviewPayload = {
  review_id: string;
  type: string;
  title?: string;
  message?: string;
  message_zh?: string;
  actions?: string[];
  items?: ReviewItem[];
  options?: ReviewOption[];
  max_selected?: number;
  recommended_mode?: string;
  safety_notice?: string;
  submission_safety?: string;
  submission_safety_zh?: string;
  required_files?: string[];
  next_stage?: string;
  temporary_model_ready?: boolean;
  temporary_model_run_id?: string;
  confirmation_phrase?: string;
  plan_digest?: string;
};

export type ReviewData = {
  taskId: string;
  review: ReviewPayload;
  historyStatus?: "waiting" | "submitted";
  submittedDecision?: Record<string, unknown>;
  submittedAt?: string;
};

export type TaskData = {
  taskId: string;
  task: CatalystTask;
};

export type StageData = {
  taskId: string;
  stage: WorkflowStage;
};

export type ConsultationData = {
  consultation: ConsultationRecord;
  pending: boolean;
};

export type CatalystUIMessage = UIMessage<
  unknown,
  { review: ReviewData; task: TaskData; stage: StageData; consultation: ConsultationData }
>;
