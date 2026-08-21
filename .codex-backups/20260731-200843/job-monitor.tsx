"use client";

import { ActivityIcon, EyeIcon, LoaderCircleIcon, RefreshCwIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { getTaskJobLog, listTaskJobs, refreshTaskJob, type CatalystJob } from "@/lib/catalyst-api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { technicalStatusLabel } from "@/lib/status-labels";

const AUTO_REFRESH_MS = 30_000;
const LOG_OPTIONS = [
  { value: "key", label: "关键日志汇总" },
  { value: "OSZICAR", label: "OSZICAR 离子步" },
  { value: "OUTCAR", label: "OUTCAR 完整输出末尾" },
  { value: "vasp.out", label: "vasp.out 标准输出" },
  { value: "slurm.out", label: "Slurm 输出" },
] as const;

type OpenLog = {
  jobId: string;
  name: string;
  content: string;
  readAt?: string;
};

export function JobMonitor({ taskId }: { taskId?: string }) {
  const [jobs, setJobs] = useState<CatalystJob[]>([]);
  const [error, setError] = useState("");
  const [initialLoading, setInitialLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [log, setLog] = useState<OpenLog | null>(null);
  const [logSource, setLogSource] = useState("key");
  const [logLoading, setLogLoading] = useState(false);
  const requestInFlight = useRef(false);

  const load = useCallback(
    async (refreshRemote = false) => {
      if (!taskId || requestInFlight.current) return;
      requestInFlight.current = true;
      setError("");
      if (jobs.length === 0) setInitialLoading(true);
      else setRefreshing(true);
      try {
        const listed = await listTaskJobs(taskId);
        if (!refreshRemote) {
          setJobs(listed);
          return;
        }
        const refreshed = await Promise.allSettled(
          listed.map((job) =>
            job.terminal ? Promise.resolve(job) : refreshTaskJob(job.slurm_job_id),
          ),
        );
        setJobs(
          refreshed.map((result, index) =>
            result.status === "fulfilled" ? result.value : listed[index],
          ),
        );
        const rejected = refreshed.find((result) => result.status === "rejected");
        if (rejected?.status === "rejected") {
          setError(`部分作业刷新失败，继续显示上次状态：${String(rejected.reason)}`);
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        requestInFlight.current = false;
        setInitialLoading(false);
        setRefreshing(false);
      }
    },
    [jobs.length, taskId],
  );

  useEffect(() => {
    setJobs([]);
    setError("");
    setLog(null);
    if (!taskId) return;
    void load(false);
  }, [taskId]);

  useEffect(() => {
    if (!taskId || !jobs.some((job) => !job.terminal)) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [jobs, load, taskId]);

  const openLog = async (jobId: string, source = logSource) => {
    setLogLoading(true);
    setError("");
    try {
      const result = await getTaskJobLog(jobId, source);
      setLog({
        jobId,
        name: result.name,
        content: result.content,
        readAt: result.read_at,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLogLoading(false);
    }
  };

  if (!taskId) {
    return <p className="p-4 text-sm text-muted-foreground">选择任务后查看 Slurm 作业。</p>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b px-3 py-3">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold">
            <ActivityIcon className="size-4" />
            DFT 作业监控
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            活动作业每 30 秒刷新，旧数据保留至新状态返回。
          </p>
        </div>
        <Button
          size="icon-sm"
          variant="ghost"
          disabled={refreshing}
          onClick={() => void load(true)}
          aria-label="刷新作业"
        >
          <RefreshCwIcon className={`size-4 ${refreshing ? "animate-spin" : ""}`} />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {jobs.map((job) => (
          <article key={job.slurm_job_id} className="mb-3 border p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="break-words text-sm font-semibold">{job.job_id}</p>
                <p className="mt-1 text-xs text-muted-foreground">Slurm {job.slurm_job_id}</p>
              </div>
              <span className={`shrink-0 text-xs font-semibold ${stateColor(job.scheduler_state)}`}>
                {technicalStatusLabel(job.scheduler_state)}
              </span>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
              <dt className="text-muted-foreground">运行时间</dt>
              <dd>{job.scheduler_elapsed || "尚未返回"}</dd>
              <dt className="text-muted-foreground">节点/原因</dt>
              <dd>{job.scheduler_detail || "-"}</dd>
              <dt className="text-muted-foreground">VASP</dt>
              <dd>{technicalStatusLabel(job.vasp_decision)}</dd>
              <dt className="text-muted-foreground">离子步</dt>
              <dd>{job.vasp_ionic_steps ?? "-"}</dd>
              {job.final_toten_ev != null && (
                <>
                  <dt className="text-muted-foreground">最终能量</dt>
                  <dd>{job.final_toten_ev} eV</dd>
                </>
              )}
            </dl>
            <div className="mt-3 flex gap-2">
              <Button size="sm" variant="outline" onClick={() => void load(true)}>
                <RefreshCwIcon className="size-3.5" />
                刷新状态
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={logLoading}
                onClick={() => void openLog(job.slurm_job_id)}
              >
                {logLoading ? (
                  <LoaderCircleIcon className="size-3.5 animate-spin" />
                ) : (
                  <EyeIcon className="size-3.5" />
                )}
                查看日志
              </Button>
            </div>
          </article>
        ))}
        {initialLoading && !jobs.length && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircleIcon className="size-4 animate-spin" /> 正在读取作业记录
          </p>
        )}
        {!initialLoading && !jobs.length && !error && (
          <p className="text-sm text-muted-foreground">此任务尚无已提交的 Slurm 作业。</p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
      <Dialog open={Boolean(log)} onOpenChange={(open) => !open && setLog(null)}>
        <DialogContent className="sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>{log?.name || "DFT 日志"}</DialogTitle>
            <DialogDescription>
              Slurm {log?.jobId} · 远程只读；切换来源不会修改或中断作业。
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <select
              className="h-9 min-w-56 border bg-background px-2 text-sm"
              value={logSource}
              onChange={(event) => setLogSource(event.target.value)}
            >
              {LOG_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              disabled={!log || logLoading}
              onClick={() => log && void openLog(log.jobId, logSource)}
            >
              <RefreshCwIcon className={`size-3.5 ${logLoading ? "animate-spin" : ""}`} />
              读取所选日志
            </Button>
            {log?.readAt && (
              <span className="text-xs text-muted-foreground">
                读取于 {new Date(log.readAt).toLocaleString("zh-CN")}
              </span>
            )}
          </div>
          <pre className="max-h-[68vh] overflow-auto whitespace-pre-wrap break-words border bg-neutral-950 p-4 font-mono text-xs leading-5 text-neutral-100">
            {log?.content || "所选日志暂时为空。"}
          </pre>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function stateColor(value: string) {
  return value === "COMPLETED"
    ? "text-emerald-700"
    : ["FAILED", "CANCELLED", "TIMEOUT"].includes(value)
      ? "text-destructive"
      : value === "RUNNING"
        ? "text-sky-700"
        : "text-amber-700";
}
