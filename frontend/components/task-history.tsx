"use client";

import { ArchiveIcon, EyeIcon, HistoryIcon, PlayIcon, SearchIcon, XIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  archiveCatalystTask,
  listCatalystTasks,
  resumeCatalystTask,
  type CatalystTaskSummary,
} from "@/lib/catalyst-api";
import { technicalStatusLabel } from "@/lib/status-labels";

export function TaskHistory({
  open,
  currentTaskId,
  onClose,
  onSelect,
}: {
  open: boolean;
  currentTaskId?: string;
  onClose: () => void;
  onSelect: (taskId: string) => void;
}) {
  const [tasks, setTasks] = useState<CatalystTaskSummary[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [message, setMessage] = useState("");

  const refresh = async () => {
    try {
      setTasks(await listCatalystTasks());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open]);

  const filtered = useMemo(
    () =>
      tasks.filter((task) => {
        const text = `${task.task_id} ${task.question} ${task.stage_label}`.toLowerCase();
        return (
          (!query || text.includes(query.toLowerCase())) &&
          (status === "all" || task.status === status)
        );
      }),
    [query, status, tasks],
  );

  if (!open) return null;
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-muted/20">
      <div className="flex items-center justify-between border-b px-3 py-3">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold">
            <HistoryIcon className="size-4" /> 历史任务
          </p>
          <p className="mt-1 text-xs text-muted-foreground">按 task_id 恢复科研记录</p>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭历史任务">
          <XIcon className="size-4" />
        </Button>
      </div>
      <div className="grid gap-2 border-b p-3">
        <label className="flex items-center gap-2 border bg-background px-2 py-1.5">
          <SearchIcon className="size-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索任务或 task_id"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </label>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="border bg-background px-2 py-1.5 text-sm"
        >
          <option value="all">全部状态</option>
          <option value="waiting_for_human">等待人工审查</option>
          <option value="running">运行中</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
        </select>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {filtered.map((task) => (
          <article
            key={task.task_id}
            className={`mb-2 border bg-background p-3 ${task.task_id === currentTaskId ? "border-foreground" : ""}`}
          >
            <button
              type="button"
              className="w-full text-left"
              onClick={() => onSelect(task.task_id)}
            >
              <p className="line-clamp-2 text-sm font-semibold">{task.question || task.task_id}</p>
              <p className="mt-1 break-all text-xs text-muted-foreground">{task.task_id}</p>
              <div className="mt-2 flex justify-between text-xs text-muted-foreground">
                <span>{task.stage_label || task.stage}</span>
                <span>{task.progress}%</span>
              </div>
              <div className="mt-1 h-1 bg-muted">
                <div className="h-full bg-emerald-600" style={{ width: `${task.progress}%` }} />
              </div>
            </button>
            <div className="mt-3 flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                {technicalStatusLabel(task.status)}
              </span>
              <div className="flex gap-1">
                {task.status === "waiting_for_human" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      const result = await resumeCatalystTask(task.task_id);
                      setMessage(result.message);
                      onSelect(task.task_id);
                    }}
                  >
                    <PlayIcon className="size-3.5" /> 继续审查
                  </Button>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => onSelect(task.task_id)}>
                    <EyeIcon className="size-3.5" /> 查看
                  </Button>
                )}
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="归档任务"
                  onClick={async () => {
                    await archiveCatalystTask(task.task_id);
                    await refresh();
                  }}
                >
                  <ArchiveIcon className="size-3.5" />
                </Button>
              </div>
            </div>
          </article>
        ))}
      </div>
      {message && <p className="border-t p-3 text-xs text-muted-foreground">{message}</p>}
    </div>
  );
}
