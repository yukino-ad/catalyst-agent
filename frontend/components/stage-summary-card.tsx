"use client";

import { CheckCircle2Icon, CircleAlertIcon, CircleXIcon, MinusCircleIcon } from "lucide-react";
import type { StageData } from "@/lib/review-types";
import { technicalStatusLabel } from "@/lib/status-labels";
import { StructurePreviewLink } from "@/components/structure-preview-link";
import { CGCNNTrainingPanel } from "@/components/cgcnn-training-panel";
import { useMemo } from "react";
import { useProgressiveCard } from "@/lib/use-progressive-card";

export function StageSummaryCard({
  data,
  animate = false,
  onRevealComplete,
}: {
  data: StageData;
  animate?: boolean;
  onRevealComplete?: () => void;
}) {
  const { stage } = data;
  const Icon =
    stage.status === "failed"
      ? CircleXIcon
      : stage.status === "skipped"
        ? MinusCircleIcon
        : stage.status === "waiting_review"
          ? CircleAlertIcon
          : CheckCircle2Icon;
  const facts = useMemo(
    () =>
      Object.entries(stage.outputs ?? {})
        .filter(([key, value]) => key !== "items" && isScalar(value))
        .slice(0, 6),
    [stage.outputs],
  );
  const items = useMemo(
    () =>
      Array.isArray(stage.outputs?.items)
        ? stage.outputs.items.filter(
            (item): item is Record<string, unknown> => Boolean(item) && typeof item === "object",
          )
        : [],
    [stage.outputs],
  );
  const lines = useMemo(
    () => [
      `${stage.stage_id} · ${stage.stage_label}`,
      technicalStatusLabel(stage.status),
      stage.summary || "该阶段已完成。",
      ...facts.map(
        ([key, value]) =>
          `${outputLabel(key)}：${key === "status" ? technicalStatusLabel(value) : String(value)}`,
      ),
      stage.next_stage && stage.next_stage !== "completed" ? `下一步：${stage.next_stage}` : "",
    ],
    [facts, stage.next_stage, stage.stage_id, stage.stage_label, stage.status, stage.summary],
  );
  const reveal = useProgressiveCard(lines, animate, onRevealComplete);
  const factsOffset = 3;
  return (
    <section className="my-3 border-y py-3" aria-label={`${stage.stage_id} 阶段摘要`}>
      <div className="flex items-start gap-3">
        <Icon
          className={`mt-0.5 size-4 shrink-0 ${stage.status === "failed" ? "text-destructive" : stage.status === "waiting_review" ? "text-amber-600" : "text-emerald-600"}`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-semibold">{reveal.text(0)}</h3>
            <span className="text-xs text-muted-foreground">{reveal.text(1)}</span>
          </div>
          <p className="mt-1 min-h-5 text-sm text-muted-foreground">{reveal.text(2)}</p>
          {facts.length > 0 && (
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              {facts.map(([key], index) => {
                const value = reveal.text(factsOffset + index);
                return value ? (
                  <div key={key} className="min-w-0 text-muted-foreground">
                    {value}
                  </div>
                ) : null;
              })}
            </dl>
          )}
          {reveal.complete && items.length > 0 && (
            <div className="mt-3 divide-y border-y">
              {items.map((item, index) => (
                <StageResultItem
                  key={String(item.structure_id ?? item.slab_id ?? index)}
                  item={item}
                  taskId={data.taskId}
                  stageId={stage.stage_id}
                />
              ))}
            </div>
          )}
          {reveal.complete && stage.stage_id === "C6" && (
            <CGCNNTrainingPanel taskId={data.taskId} />
          )}
          {stage.next_stage && stage.next_stage !== "completed" && (
            <p className="mt-2 text-xs text-muted-foreground">
              {reveal.text(factsOffset + facts.length)}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function StageResultItem({
  item,
  taskId,
  stageId,
}: {
  item: Record<string, unknown>;
  taskId: string;
  stageId: string;
}) {
  const identity = String(item.structure_id ?? item.slab_id ?? item.candidate_id ?? "结构结果");
  const composition =
    item.composition && typeof item.composition === "object"
      ? Object.entries(item.composition as Record<string, unknown>)
          .map(([key, value]) => `${key}${value}`)
          .join(" ")
      : Array.isArray(item.elements)
        ? item.elements.join(" ")
        : "";
  return (
    <div className="py-2 text-xs">
      <p className="break-all font-semibold">{identity}</p>
      {composition && <p className="mt-1 text-muted-foreground">组成：{composition}</p>}
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
        {item.formation_energy_ev_per_atom != null && (
          <span>
            形成能：{formatNumber(item.formation_energy_ev_per_atom)}{" "}
            {String(item.formation_energy_unit ?? "eV/atom")}
          </span>
        )}
        {item.delta_percent != null && <span>δ：{formatNumber(item.delta_percent)}%</span>}
        {item.omega != null && <span>Ω：{formatNumber(item.omega)}</span>}
        {item.stability_decision != null && (
          <span>判据：{technicalStatusLabel(item.stability_decision)}</span>
        )}
        {item.formation_energy_status != null && (
          <span>预测：{technicalStatusLabel(item.formation_energy_status)}</span>
        )}
      </div>
      {(stageId === "C5" || stageId === "C12.3" || stageId === "C12.4") &&
        (item.structure_id != null || item.adsorption_structure_id != null) && (
          <StructurePreviewLink
            taskId={taskId}
            structureLabel={String(item.structure_id ?? item.adsorption_structure_id)}
            linkLabel={stageId.startsWith("C12") ? "查看吸附结构" : "查看三维结构"}
          />
        )}
    </div>
  );
}

function formatNumber(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")
    : String(value);
}

function isScalar(value: unknown): value is string | number | boolean | null {
  return value == null || ["string", "number", "boolean"].includes(typeof value);
}

function outputLabel(key: string) {
  return (
    (
      {
        candidate_count: "候选数",
        selected_count: "保留数",
        passed_count: "通过数",
        failed_count: "失败数",
        bundle_count: "输入包数",
        job_count: "作业数",
        structure_count: "结构数",
        slab_count: "slab 数",
        calculation_count: "计算数",
        approved_count: "批准数",
        rejected_count: "拒绝数",
        formation_energy_ev_per_atom: "形成能",
        delta_percent: "δ (%)",
        omega: "Ω",
        status: "结果状态",
      } as Record<string, string>
    )[key] ?? key
  );
}
