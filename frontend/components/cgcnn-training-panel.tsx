"use client";

import { BrainCircuitIcon, ChevronDownIcon, ChevronUpIcon, XIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  getCGCNNTraining,
  getCGCNNTrainingLog,
  getLatestCGCNNTraining,
  startCGCNNTraining,
  type CGCNNTraining,
} from "@/lib/catalyst-api";
import { technicalStatusLabel } from "@/lib/status-labels";

export function CGCNNTrainingPanel({ taskId }: { taskId: string }) {
  const [training, setTraining] = useState<CGCNNTraining | null>(null);
  const [log, setLog] = useState("");
  const [open, setOpen] = useState(true);
  const [visible, setVisible] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    void getLatestCGCNNTraining(taskId)
      .then(setTraining)
      .catch(() => undefined);
  }, [taskId]);

  useEffect(() => {
    if (!training?.run_id || !visible) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const [next, logs] = await Promise.all([
          getCGCNNTraining(taskId, training.run_id),
          getCGCNNTrainingLog(taskId, training.run_id),
        ]);
        if (cancelled) return;
        setTraining(next);
        setLog(logs.content);
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      }
    };
    void refresh();
    const terminal = ["completed", "failed"].includes(training.status);
    const timer = terminal ? undefined : window.setInterval(() => void refresh(), 1500);
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [taskId, training?.run_id, training?.status, visible]);

  const start = async () => {
    setError("");
    setVisible(true);
    setOpen(true);
    try {
      setTraining(await startCGCNNTraining(taskId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  if (!visible) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-3"
        onClick={() => setVisible(true)}
      >
        <BrainCircuitIcon className="size-4" />
        显示临时 CGCNN 训练
      </Button>
    );
  }

  return (
    <div className="mt-3 border-y py-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">可选：临时训练 CGCNN</p>
          <p className="text-xs text-muted-foreground">
            使用固定 560/70/70 数据划分训练 30 轮；不会替换生产模型。
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title={open ? "收起日志" : "展开日志"}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <ChevronUpIcon className="size-4" /> : <ChevronDownIcon className="size-4" />}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="关闭训练面板"
            onClick={() => setVisible(false)}
          >
            <XIcon className="size-4" />
          </Button>
        </div>
      </div>
      {!training && (
        <Button type="button" size="sm" className="mt-3" onClick={() => void start()}>
          <BrainCircuitIcon className="size-4" />
          开始临时训练
        </Button>
      )}
      {training && (
        <div className="mt-3 text-xs">
          <p>{technicalStatusLabel(training.status)}</p>
          <p className="mt-1 text-muted-foreground">{training.message}</p>
          {training.metrics && (
            <p className="mt-1">
              MAE {formatMetric(training.metrics.mae)} · RMSE {formatMetric(training.metrics.rmse)}{" "}
              · R² {formatMetric(training.metrics.r2)}
            </p>
          )}
          {training.status === "failed" && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="mt-2"
              onClick={() => void start()}
            >
              重新训练
            </Button>
          )}
        </div>
      )}
      {open && training && (
        <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words bg-neutral-950 p-3 font-mono text-xs leading-5 text-neutral-100">
          {log || "等待 CGCNN 输出..."}
        </pre>
      )}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
    </div>
  );
}

function formatMetric(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(6) : "--";
}
