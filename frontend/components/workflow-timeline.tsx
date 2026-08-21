"use client";

import {
  BanIcon,
  CheckCircle2Icon,
  CircleAlertIcon,
  CircleIcon,
  CircleXIcon,
  LoaderCircleIcon,
  MinusCircleIcon,
} from "lucide-react";
import { useState } from "react";
import type { WorkflowStage } from "@/lib/catalyst-api";
import { technicalStatusLabel } from "@/lib/status-labels";

const GROUPS = [
  { id: "A", label: "A 阶段 · 任务理解" },
  { id: "B", label: "B 阶段 · 文献证据" },
  { id: "C", label: "C 阶段 · 候选、结构和 DFT" },
  { id: "C12", label: "C12 · 吸附计算" },
] as const;

export function WorkflowTimeline({
  stages,
  currentStage,
}: {
  stages: WorkflowStage[];
  currentStage?: string;
}) {
  const [expanded, setExpanded] = useState<string | null>(currentStage ?? null);
  if (!stages.length)
    return <p className="p-4 text-sm text-muted-foreground">任务阶段正在准备，请稍候。</p>;
  return (
    <aside className="flex h-full min-h-0 w-[290px] shrink-0 flex-col border-r bg-muted/20">
      <div className="border-b px-4 py-4">
        <p className="text-sm font-semibold">任务进度</p>
        <p className="mt-1 text-xs text-muted-foreground">A1 至 C12.7 全部阶段</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {GROUPS.map((group) => {
          const groupStages = stages.filter((stage) => stage.group === group.id);
          if (!groupStages.length) return null;
          return (
            <section key={group.id} className="mb-4 last:mb-0">
              <h2 className="mb-2 px-2 text-xs font-semibold text-muted-foreground">
                {group.label}
              </h2>
              <div className="space-y-1">
                {groupStages.map((stage) => (
                  <TimelineStage
                    key={stage.stage_id}
                    stage={stage}
                    active={stage.stage_id === currentStage}
                    expanded={expanded === stage.stage_id}
                    onToggle={() =>
                      setExpanded((value) => (value === stage.stage_id ? null : stage.stage_id))
                    }
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </aside>
  );
}

function TimelineStage({
  stage,
  active,
  expanded,
  onToggle,
}: {
  stage: WorkflowStage;
  active: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  const Icon = statusIcon(stage.status);
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`w-full border px-2.5 py-2 text-left transition-colors ${active ? "border-foreground bg-background" : "border-transparent hover:border-border hover:bg-background/70"}`}
      aria-expanded={expanded}
    >
      <span className="flex items-start gap-2">
        <Icon className={`mt-0.5 size-4 shrink-0 ${statusColor(stage.status)}`} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className="text-xs font-semibold">{stage.stage_id}</span>
            <span className="truncate text-xs text-muted-foreground">
              {technicalStatusLabel(stage.status)}
            </span>
          </span>
          <span className="mt-0.5 block text-sm leading-5">{displayStageLabel(stage)}</span>
          {stage.requires_human_action && (
            <span className="mt-1 inline-block text-xs font-semibold text-amber-700">
              需要人工操作
            </span>
          )}
          {expanded && (
            <span className="mt-2 block border-t pt-2 text-xs leading-5 text-muted-foreground">
              {stage.summary || technicalStatusLabel(stage.status)}
              {stage.skip_reason && <span className="mt-1 block">原因：{stage.skip_reason}</span>}
              {stage.error && (
                <span className="mt-1 block text-destructive">错误：{stage.error}</span>
              )}
              {(stage.next_stage || stage.next) &&
                (stage.next_stage || stage.next) !== "completed" && (
                  <span className="mt-1 block">下一步：{stage.next_stage || stage.next}</span>
                )}
            </span>
          )}
        </span>
      </span>
    </button>
  );
}

function displayStageLabel(stage: WorkflowStage) {
  const labels: Record<string, string> = {
    A1: "理解任务",
    A2: "检查能力",
    A3: "选择工作流分支",
    A4: "生成任务计划",
    B1: "召回文献",
    B2: "检查文献元数据",
    B3: "分析任务相关性",
    B4: "联网检索学术文献",
    B5: "提取证据和科学断言",
    B6: "人工审查文献",
    C1: "准备候选约束",
    C2: "生成候选组合",
    C3: "排序候选组合",
    C4: "人工选择候选",
    C5: "建立 FCC bulk",
    C6: "预测形成能",
    C7: "执行稳定性判据",
    C8: "构建表面 slab",
    C9: "检查 slab 质量",
    C10: "准备 DFT 输入",
    C11: "提交和监控 DFT",
    "C12.1": "选择吸附中间体",
    "C12.2": "接收弛豫后 clean slab",
    "C12.3": "建立吸附位点结构",
    "C12.4": "检查吸附结构",
    "C12.5": "准备吸附 DFT 输入",
    "C12.6": "监控吸附 DFT",
    "C12.7": "审查吸附能",
  };
  return labels[stage.stage_id] ?? stage.stage_label ?? stage.label;
}

function statusIcon(status: WorkflowStage["status"]) {
  if (status === "completed") return CheckCircle2Icon;
  if (status === "running") return LoaderCircleIcon;
  if (status === "waiting_review") return CircleAlertIcon;
  if (status === "skipped") return MinusCircleIcon;
  if (status === "blocked") return BanIcon;
  if (status === "failed") return CircleXIcon;
  return CircleIcon;
}

function statusColor(status: WorkflowStage["status"]) {
  if (status === "completed") return "text-emerald-600";
  if (status === "running") return "animate-spin text-sky-600";
  if (status === "waiting_review") return "text-amber-600";
  if (status === "failed") return "text-destructive";
  return "text-muted-foreground";
}
