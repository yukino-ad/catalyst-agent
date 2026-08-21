"use client";

import {
  BookOpenTextIcon,
  CirclePauseIcon,
  CopyIcon,
  FileTextIcon,
  PlayIcon,
  Settings2Icon,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { continueConsultedWorkflow, type ConsultationRecord } from "@/lib/catalyst-api";

export function ConsultationCard({
  consultation,
  pending,
  inline = false,
}: {
  consultation: ConsultationRecord;
  pending: boolean;
  inline?: boolean;
}) {
  const [status, setStatus] = useState<"idle" | "continuing" | "continued" | "error">(
    consultation.continued ? "continued" : "idle",
  );
  const [message, setMessage] = useState("");
  const Icon =
    consultation.intent === "vasp_consultation"
      ? Settings2Icon
      : consultation.intent === "report_request"
        ? FileTextIcon
        : BookOpenTextIcon;
  const continueWorkflow = async () => {
    setStatus("continuing");
    try {
      const result = await continueConsultedWorkflow(
        consultation.task_id,
        consultation.consultation_id,
      );
      setStatus("continued");
      setMessage(result.message || "工作流已继续。");
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };
  return (
    <section
      className={
        inline
          ? "mt-4 border-t border-sky-200 pt-3"
          : "my-4 border-y border-sky-200 bg-sky-50/40 py-4"
      }
      aria-label="科研咨询记录"
    >
      <div className="flex items-start gap-3 px-1">
        <Icon className="mt-0.5 size-4 shrink-0 text-sky-700" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-semibold">{intentLabel(consultation.intent)}</h3>
            <span className="text-xs text-muted-foreground">
              {sourceLabel(consultation.answer_source)}
            </span>
          </div>
          {!inline && (
            <>
              <p className="mt-2 text-xs font-semibold text-muted-foreground">用户问题</p>
              <p className="mt-1 text-sm">{consultation.question}</p>
              <p className="mt-3 text-xs font-semibold text-muted-foreground">Agent 回答</p>
              <div className="mt-1 whitespace-pre-wrap text-sm leading-6">
                {consultation.answer}
              </div>
            </>
          )}
          {consultation.answer_recovery_note && (
            <p className="mt-2 text-xs text-amber-700">
              历史 Kimi 回答为空，当前展示的是本地规则生成的说明。
            </p>
          )}
          {consultation.intent === "vasp_consultation" && (
            <Button
              className="mt-3"
              type="button"
              size="sm"
              variant="outline"
              onClick={async () => {
                await navigator.clipboard.writeText(consultation.answer);
                setMessage("修改建议已复制。请粘贴到当前 C10/C12.5 修订框并重新人工确认。 ");
              }}
            >
              <CopyIcon className="size-4" />
              复制为受控修改建议
            </Button>
          )}
          {consultation.report && (
            <div className="mt-3 flex flex-wrap gap-2">
              <ReportLink taskId={consultation.task_id} format="html" label="打开网页报告" />
              <ReportLink taskId={consultation.task_id} format="md" label="下载 Markdown" />
              <ReportLink taskId={consultation.task_id} format="json" label="下载 JSON" />
            </div>
          )}
          {consultation.requires_continue_confirmation && (
            <div className="mt-4 border-s-4 border-amber-500 bg-amber-50 px-3 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <CirclePauseIcon className="size-4" />
                工作流控制
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                咨询不会修改科研状态。继续只会从当前 checkpoint 的下一节点恢复。
              </p>
              {pending && status !== "continued" ? (
                <div className="mt-3 flex gap-2">
                  <Button
                    size="sm"
                    disabled={status === "continuing"}
                    onClick={() => void continueWorkflow()}
                  >
                    <PlayIcon className="size-4" />
                    {status === "continuing" ? "正在继续" : "继续工作流"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    type="button"
                    onClick={() => setMessage("工作流保持在当前节点边界；稍后仍可点击继续。")}
                  >
                    保持暂停
                  </Button>
                </div>
              ) : (
                <p className="mt-2 text-xs text-emerald-700">已确认继续，或原任务无需恢复。</p>
              )}
              {message && (
                <p
                  className={`mt-2 text-xs ${status === "error" ? "text-destructive" : "text-muted-foreground"}`}
                >
                  {message}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function ReportLink({ taskId, format, label }: { taskId: string; format: string; label: string }) {
  return (
    <a
      className="text-sm font-semibold text-sky-700 underline underline-offset-4"
      href={`/api/tasks/${encodeURIComponent(taskId)}/report/download?format=${format}`}
      target="_blank"
      rel="noreferrer"
    >
      {label}
    </a>
  );
}

function intentLabel(intent: ConsultationRecord["intent"]) {
  return {
    workflow_command: "工作流操作说明",
    vasp_consultation: "VASP 参数咨询",
    scientific_explanation: "科研概念解释",
    report_request: "任务报告",
    general_research_chat: "电催化科研问答",
  }[intent];
}

function sourceLabel(source: ConsultationRecord["answer_source"]) {
  return {
    kimi: "kimi · Kimi",
    local_rules: "local_rules · 本地规则",
    local_fallback: "local_fallback · Kimi 失败后本地回退",
  }[source];
}
