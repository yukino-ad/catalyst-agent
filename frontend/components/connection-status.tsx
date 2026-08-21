"use client";

import { RefreshCwIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";

type StateName = "not_configured" | "configured_not_checked" | "checking" | "connected" | "failed";

type Connection = {
  configured: boolean;
  status: StateName;
  label: string;
  detail: string;
};

type ConnectionPayload = {
  checked_at: string;
  kimi: Connection;
  cluster: Connection;
  remote_operations: {
    web_enabled: boolean;
    upload_enabled: boolean;
    submission_enabled: boolean;
  };
};

export function ConnectionStatusBar() {
  const [data, setData] = useState<ConnectionPayload | null>(null);
  const [checking, setChecking] = useState(false);

  const check = async () => {
    setChecking(true);
    try {
      const response = await fetch("/api/system/connections", { method: "POST" });
      if (!response.ok) throw new Error(`连接检查失败 (${response.status})`);
      setData((await response.json()) as ConnectionPayload);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setData({
        checked_at: new Date().toISOString(),
        kimi: { configured: false, status: "failed", label: "Kimi", detail },
        cluster: { configured: false, status: "failed", label: "HPC", detail },
        remote_operations: { web_enabled: false, upload_enabled: false, submission_enabled: false },
      });
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    void check();
  }, []);

  return (
    <div className="flex items-center gap-1.5" aria-label="外部服务连接状态">
      <StatusPill connection={data?.kimi} fallbackLabel="Kimi" checking={checking} />
      <StatusPill connection={data?.cluster} fallbackLabel="超算" checking={checking} />
      <TooltipIconButton
        tooltip="重新检查 Kimi 与超算连接"
        variant="ghost"
        size="icon"
        disabled={checking}
        onClick={() => void check()}
        aria-label="刷新连接状态"
        className="size-7"
      >
        <RefreshCwIcon className={`size-3.5 ${checking ? "animate-spin" : ""}`} />
      </TooltipIconButton>
    </div>
  );
}

function StatusPill({
  connection,
  fallbackLabel,
  checking,
}: {
  connection?: Connection;
  fallbackLabel: string;
  checking: boolean;
}) {
  const status = checking ? "checking" : (connection?.status ?? "configured_not_checked");
  const label = connection?.label === "HPC" ? "超算" : (connection?.label ?? fallbackLabel);
  const color = {
    connected: "bg-emerald-500",
    failed: "bg-red-500",
    not_configured: "bg-zinc-400",
    configured_not_checked: "bg-amber-500",
    checking: "bg-amber-500 animate-pulse",
  }[status];
  const stateLabel = {
    connected: "已连接",
    failed: "连接失败",
    not_configured: "未配置",
    configured_not_checked: "待检查",
    checking: "检查中",
  }[status];
  return (
    <span
      className="inline-flex h-7 items-center gap-1.5 border px-2 text-xs"
      title={`${label}：${connection?.detail ?? stateLabel}`}
    >
      <span className={`size-2 rounded-full ${color}`} aria-hidden="true" />
      {label} {stateLabel}
    </span>
  );
}
