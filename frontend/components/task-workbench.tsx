"use client";

import { ActivityIcon, FilesIcon, HistoryIcon, PanelRightCloseIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { FileCenter } from "@/components/file-center";
import { JobMonitor } from "@/components/job-monitor";
import { TaskHistory } from "@/components/task-history";

type Tab = "tasks" | "files" | "jobs";

export function TaskWorkbench({
  taskId,
  onSelectTask,
  onClose,
}: {
  taskId?: string;
  onSelectTask: (taskId: string) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("tasks");
  return (
    <aside className="flex h-full w-[360px] shrink-0 flex-col border-l bg-background">
      <div className="flex items-center gap-1 border-b p-2">
        <TabButton
          active={tab === "tasks"}
          label="任务"
          icon={<HistoryIcon />}
          onClick={() => setTab("tasks")}
        />
        <TabButton
          active={tab === "files"}
          label="文件"
          icon={<FilesIcon />}
          onClick={() => setTab("files")}
        />
        <TabButton
          active={tab === "jobs"}
          label="DFT"
          icon={<ActivityIcon />}
          onClick={() => setTab("jobs")}
        />
        <Button
          size="icon-sm"
          variant="ghost"
          className="ml-auto"
          onClick={onClose}
          aria-label="收起右侧工作台"
        >
          <PanelRightCloseIcon className="size-4" />
        </Button>
      </div>
      <div className="flex min-h-0 flex-1">
        {tab === "tasks" && (
          <TaskHistory open currentTaskId={taskId} onClose={onClose} onSelect={onSelectTask} />
        )}
        {tab === "files" && <FileCenter taskId={taskId} />}
        {tab === "jobs" && <JobMonitor taskId={taskId} />}
      </div>
    </aside>
  );
}

function TabButton({
  active,
  label,
  icon,
  onClick,
}: {
  active: boolean;
  label: string;
  icon: ReactNode;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant={active ? "secondary" : "ghost"}
      onClick={onClick}
      className="gap-1.5"
    >
      <span className="[&_svg]:size-4">{icon}</span>
      {label}
    </Button>
  );
}
