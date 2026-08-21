"use client";

import { AssistantRuntimeProvider, useAssistantRuntime, useAuiState } from "@assistant-ui/react";
import { useChatRuntime, AssistantChatTransport } from "@assistant-ui/react-ai-sdk";
import { lastAssistantMessageIsCompleteWithToolCalls } from "ai";
import { MessageSquarePlusIcon, PanelRightOpenIcon, Trash2Icon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { getCatalystTask, type CatalystTask } from "@/lib/catalyst-api";
import { WorkflowTimeline } from "@/components/workflow-timeline";
import { TaskWorkbench } from "@/components/task-workbench";
import { Thread } from "@/components/assistant-ui/thread";
import type { TaskData } from "@/lib/review-types";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import { ConnectionStatusBar } from "@/components/connection-status";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export const Assistant = () => {
  const runtime = useChatRuntime({
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithToolCalls,
    transport: new AssistantChatTransport({
      api: "/api/chat",
    }),
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <AssistantShell />
    </AssistantRuntimeProvider>
  );
};

const AssistantShell = () => {
  const messages = useAuiState((state) => state.thread.messages);
  const [task, setTask] = useState<CatalystTask | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [workbenchOpen, setWorkbenchOpen] = useState(true);
  const lastConversationTaskId = useRef("");
  const pollingInFlight = useRef(false);

  const conversationTaskRef = useMemo(() => {
    const taskRefs = messages
      .filter((message) => message.role === "assistant")
      .flatMap((message) => message.parts)
      .filter(
        (part): part is Extract<(typeof messages)[number]["parts"][number], { type: "data" }> =>
          part.type === "data" && part.name === "task",
      )
      .map((part) => part.data as TaskData)
      .filter((data) => Boolean(data.taskId));
    return taskRefs.at(-1);
  }, [messages]);
  const conversationTaskId = conversationTaskRef?.taskId ?? "";

  useEffect(() => {
    // Older F4.5 builds persisted the selected history task across page reloads.
    window.localStorage.removeItem("catalyst:last-task-id");
  }, []);

  useEffect(() => {
    if (!conversationTaskId || conversationTaskId === lastConversationTaskId.current) return;
    lastConversationTaskId.current = conversationTaskId;
    setSelectedTaskId(conversationTaskId);
    if (conversationTaskRef) setTask(conversationTaskRef.task);
  }, [conversationTaskId, conversationTaskRef]);

  useEffect(() => {
    const taskId = selectedTaskId;
    if (!taskId) return;
    let cancelled = false;
    const refresh = async () => {
      if (pollingInFlight.current || document.visibilityState !== "visible") return;
      pollingInFlight.current = true;
      try {
        const latest = await getCatalystTask(taskId);
        if (!cancelled) {
          setTask((current) => {
            if (
              current?.task_id === latest.task_id &&
              current.updated_at === latest.updated_at &&
              current.status === latest.status
            ) {
              return current;
            }
            return latest;
          });
        }
      } catch {
        // The conversation remains usable if the task API is briefly unavailable.
      } finally {
        pollingInFlight.current = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedTaskId]);

  const selectTask = (taskId: string) => {
    setSelectedTaskId(taskId);
  };

  const resetTaskSelection = () => {
    setSelectedTaskId("");
    setTask(null);
    lastConversationTaskId.current = "";
    window.localStorage.removeItem("catalyst:last-task-id");
  };

  return (
    <div className="flex h-dvh flex-col bg-background">
      <header className="flex h-14 shrink-0 items-center justify-between border-b px-4 md:px-6">
        <div className="flex items-center gap-4">
          <div>
            <p className="text-sm font-semibold">Catalyst Agent</p>
            <p className="text-xs text-muted-foreground">电催化剂研究工作台</p>
          </div>
          <ConnectionStatusBar />
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-md border px-2 py-1 text-xs text-muted-foreground">
            F4 · Agent 已连接
          </span>
          {!workbenchOpen && (
            <TooltipIconButton
              tooltip="打开任务工作台"
              variant="ghost"
              size="icon"
              onClick={() => setWorkbenchOpen(true)}
              aria-label="打开任务工作台"
            >
              <PanelRightOpenIcon className="size-4" />
            </TooltipIconButton>
          )}
          <NewConversationButton onReset={resetTaskSelection} />
          <DeleteConversationButton onReset={resetTaskSelection} />
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <WorkflowTimeline
          stages={task?.workflow_timeline ?? []}
          currentStage={
            task?.workflow_timeline?.find((stage) => stage.status === "waiting_review")?.stage_id ??
            task?.workflow_timeline?.find((stage) => stage.status === "running")?.stage_id
          }
        />
        <main className="min-w-0 flex-1">
          <Thread
            task={task}
            embedWorkflowRecord={Boolean(task && task.task_id === conversationTaskId)}
          />
        </main>
        {workbenchOpen && (
          <TaskWorkbench
            taskId={task?.task_id}
            onSelectTask={selectTask}
            onClose={() => setWorkbenchOpen(false)}
          />
        )}
      </div>
    </div>
  );
};

const NewConversationButton = ({ onReset }: { onReset: () => void }) => {
  const runtime = useAssistantRuntime();
  const isRunning = useAuiState((state) => state.thread.isRunning);

  const startNewConversation = async () => {
    const messages = [...runtime.thread.getState().messages].reverse();
    for (const message of messages) {
      await runtime.thread.deleteMessage(message.id);
    }
    await runtime.thread.composer.reset();
    onReset();
  };

  return (
    <TooltipIconButton
      tooltip={isRunning ? "任务运行时不能新建对话" : "新建对话"}
      variant="ghost"
      size="icon"
      disabled={isRunning}
      onClick={() => void startNewConversation()}
      aria-label="新建对话"
    >
      <MessageSquarePlusIcon className="size-4" />
    </TooltipIconButton>
  );
};

const DeleteConversationButton = ({ onReset }: { onReset: () => void }) => {
  const runtime = useAssistantRuntime();
  const messageCount = useAuiState((state) => state.thread.messages.length);
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const [open, setOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const deleteConversation = async () => {
    setIsDeleting(true);
    try {
      const messages = [...runtime.thread.getState().messages].reverse();
      for (const message of messages) {
        await runtime.thread.deleteMessage(message.id);
      }
      await runtime.thread.composer.reset();
      onReset();
      setOpen(false);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <TooltipIconButton
            tooltip={isRunning ? "回复完成后可删除" : "删除当前对话"}
            variant="ghost"
            size="icon"
            disabled={messageCount === 0 || isRunning}
            aria-label="删除当前对话"
          />
        }
      >
        <Trash2Icon className="size-4" />
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>删除当前对话？</DialogTitle>
          <DialogDescription>
            这会清空当前网页中的全部消息，但不会删除已经创建的 task_id、科研结果、DFT
            文件或超算作业。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" disabled={isDeleting} />}>
            取消
          </DialogClose>
          <Button variant="destructive" disabled={isDeleting} onClick={deleteConversation}>
            <Trash2Icon className="size-4" />
            {isDeleting ? "正在删除" : "确认删除"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
