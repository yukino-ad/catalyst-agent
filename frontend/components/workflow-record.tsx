"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { CatalystTask, ConsultationRecord, StageEvent } from "@/lib/catalyst-api";
import type { ReviewData, ReviewPayload } from "@/lib/review-types";
import { ReviewCard } from "@/components/review-card";
import { StageSummaryCard } from "@/components/stage-summary-card";
import { ConsultationCard } from "@/components/consultation-card";

type RecordEntry =
  | { id: string; time: string; kind: "stage"; event: StageEvent }
  | { id: string; time: string; kind: "review"; data: ReviewData }
  | { id: string; time: string; kind: "consultation"; data: ConsultationRecord };

export function WorkflowRecord({
  task,
  includeConsultations = true,
  afterTime = "",
  beforeTime = "",
  showCompletion = true,
}: {
  task: CatalystTask | null;
  includeConsultations?: boolean;
  afterTime?: string;
  beforeTime?: string;
  showCompletion?: boolean;
}) {
  const entries = useMemo(
    () => (task ? buildEntries(task, includeConsultations, afterTime, beforeTime) : []),
    [afterTime, beforeTime, includeConsultations, task],
  );
  const [revealedCount, setRevealedCount] = useState(0);
  const [completedEntryIds, setCompletedEntryIds] = useState<Set<string>>(() => new Set());
  const taskId = task?.task_id ?? "";
  const entryIds = useMemo(() => entries.map((entry) => entry.id), [entries]);
  const entryIdsKey = entryIds.join("\u0000");

  useEffect(() => {
    setRevealedCount(taskId ? 1 : 0);
    setCompletedEntryIds((current) => (current.size === 0 ? current : new Set()));
  }, [taskId]);

  const lastVisibleEntryId = entryIds[Math.max(0, revealedCount - 1)] ?? "";
  useEffect(() => {
    if (
      !taskId ||
      revealedCount >= entryIds.length ||
      !lastVisibleEntryId ||
      !completedEntryIds.has(lastVisibleEntryId)
    ) {
      return;
    }
    setRevealedCount((count) => Math.min(count + 1, entryIds.length));
  }, [completedEntryIds, entryIds.length, entryIdsKey, lastVisibleEntryId, revealedCount, taskId]);

  const finishEntry = useCallback((entryId: string) => {
    setCompletedEntryIds((current) => {
      if (current.has(entryId)) return current;
      const next = new Set(current);
      next.add(entryId);
      return next;
    });
  }, []);

  if (!task) return null;
  if (!entries.length) return null;
  const visibleEntries = entries.slice(0, revealedCount);
  const allRevealed = revealedCount >= entries.length;
  return (
    <section className="mt-2" aria-label="完整工作流记录">
      {showCompletion && task.status === "completed" && task.message && allRevealed && (
        <div className="my-4 border-s-4 border-emerald-600 bg-emerald-50 px-4 py-3">
          <p className="text-sm font-semibold">任务已结束</p>
          <p className="mt-1 text-sm text-muted-foreground">{task.message}</p>
        </div>
      )}
      {visibleEntries.map((entry, index) =>
        entry.kind === "stage" ? (
          <StageSummaryCard
            key={entry.id}
            data={{ taskId: task.task_id, stage: entry.event.stage }}
            animate={index === visibleEntries.length - 1 && !completedEntryIds.has(entry.id)}
            onRevealComplete={() => finishEntry(entry.id)}
          />
        ) : entry.kind === "review" ? (
          <ReviewCard
            key={entry.id}
            data={entry.data}
            animate={index === visibleEntries.length - 1 && !completedEntryIds.has(entry.id)}
            onRevealComplete={() => finishEntry(entry.id)}
          />
        ) : (
          <RecordedConsultation
            key={entry.id}
            consultation={entry.data}
            pending={task.consultation_pending_continue && !entry.data.continued}
            onReady={() => finishEntry(entry.id)}
          />
        ),
      )}
    </section>
  );
}

function RecordedConsultation({
  consultation,
  pending,
  onReady,
}: {
  consultation: ConsultationRecord;
  pending: boolean;
  onReady: () => void;
}) {
  useEffect(() => {
    onReady();
  }, [onReady]);
  return <ConsultationCard consultation={consultation} pending={pending} />;
}

function buildEntries(
  task: CatalystTask,
  includeConsultations: boolean,
  afterTime: string,
  beforeTime: string,
): RecordEntry[] {
  const stageEvents = [...(task.stage_events ?? [])];
  const recordedStageIds = new Set(stageEvents.map((event) => event.stage.stage_id));
  for (const stage of task.workflow_timeline) {
    if (
      recordedStageIds.has(stage.stage_id) ||
      !["completed", "waiting_review", "failed"].includes(stage.status)
    ) {
      continue;
    }
    stageEvents.push({
      event_id: `legacy-${stage.stage_id}-${stage.updated_at}`,
      node_id: stage.stage_id,
      created_at: stage.updated_at || stage.completed_at || stage.started_at,
      stage,
    });
  }
  const entries: RecordEntry[] = stageEvents.map((event) => ({
    id: `stage-${event.event_id}`,
    time: event.created_at,
    kind: "stage",
    event,
  }));
  if (includeConsultations) {
    for (const consultation of task.consultation_history ?? []) {
      entries.push({
        id: `consultation-${consultation.consultation_id}`,
        time: consultation.created_at,
        kind: "consultation",
        data: consultation,
      });
    }
  }
  for (const item of task.review_history ?? []) {
    entries.push({
      id: `review-${item.review_id}`,
      time: item.created_at,
      kind: "review",
      data: {
        taskId: task.task_id,
        review: item.review as unknown as ReviewPayload,
        historyStatus: item.status,
        submittedDecision: item.decision,
        submittedAt: item.submitted_at,
      },
    });
  }
  const currentReview = task.review as unknown as ReviewPayload;
  if (
    task.status === "waiting_for_human" &&
    currentReview?.review_id &&
    !entries.some(
      (entry) => entry.kind === "review" && entry.data.review.review_id === currentReview.review_id,
    )
  ) {
    entries.push({
      id: `review-current-${currentReview.review_id}`,
      time: task.updated_at,
      kind: "review",
      data: {
        taskId: task.task_id,
        review: currentReview,
        historyStatus: "waiting",
      },
    });
  }
  return entries
    .filter((entry) => !afterTime || entry.time > afterTime)
    .filter((entry) => !beforeTime || entry.time <= beforeTime)
    .sort((left, right) => left.time.localeCompare(right.time));
}
