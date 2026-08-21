import {
  ComposerAddAttachment,
  ComposerAttachments,
  UserMessageAttachments,
} from "@/components/assistant-ui/attachment";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import { WorkflowRecord } from "@/components/workflow-record";
import { ConsultationCard } from "@/components/consultation-card";
import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  ActionBarMorePrimitive,
  ActionBarPrimitive,
  AuiIf,
  type AssistantState,
  BranchPickerPrimitive,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  unstable_useComposerInput,
  useAuiState,
  useComposerRuntime,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  MicIcon,
  MoreHorizontalIcon,
  PencilIcon,
  RefreshCwIcon,
  SquareIcon,
} from "lucide-react";
import { useRef, type FC, type KeyboardEvent } from "react";
import type { CatalystTask } from "@/lib/catalyst-api";
import type { ConsultationData, TaskData } from "@/lib/review-types";

// Startup exposes a loading placeholder thread; treat it as a new chat so
// the composer mounts centered. Loads after startup keep the docked layout.
const isNewChatView = (s: AssistantState) =>
  s.thread.messages.length === 0 && (!s.thread.isLoading || s.threads.isLoading);

export const Thread: FC<{
  task?: CatalystTask | null;
  embedWorkflowRecord?: boolean;
}> = ({ task = null, embedWorkflowRecord = false }) => {
  const isEmpty = useAuiState(isNewChatView);
  const inlineConsultationIdKey = useAuiState((state) =>
    state.thread.messages
      .flatMap((message) => message.parts)
      .map((part) => {
        const value = part as unknown as {
          type?: string;
          name?: string;
          data?: ConsultationData;
        };
        return value.type === "data" && value.name === "consultation"
          ? (value.data?.consultation.consultation_id ?? "")
          : "";
      })
      .filter(Boolean)
      .join("|"),
  );
  const inlineConsultationIds = inlineConsultationIdKey.split("|").filter(Boolean);
  const hasEmbeddedHistory =
    embedWorkflowRecord &&
    (task?.consultation_history ?? []).every((consultation) =>
      inlineConsultationIds.includes(consultation.consultation_id),
    );

  return (
    <ThreadPrimitive.Root
      className="aui-root aui-thread-root bg-background @container flex h-full flex-col"
      style={{
        ["--thread-max-width" as string]: "44rem",
        ["--composer-bg" as string]:
          "color-mix(in oklab, var(--color-muted) 30%, var(--color-background))",
        ["--composer-radius" as string]: "1.5rem",
        ["--composer-padding" as string]: "8px",
      }}
    >
      <ThreadPrimitive.Viewport
        turnAnchor="top"
        autoScroll
        scrollToBottomOnRunStart
        scrollToBottomOnInitialize
        scrollToBottomOnThreadSwitch
        data-slot="aui_thread-viewport"
        className="relative flex flex-1 flex-col overflow-x-auto overflow-y-scroll scroll-smooth"
      >
        <div
          className={cn(
            "mx-auto flex w-full max-w-(--thread-max-width) flex-1 flex-col px-4 pt-4",
            isEmpty && "justify-center",
          )}
        >
          <AuiIf condition={isNewChatView}>
            <ThreadWelcome />
          </AuiIf>

          <div data-slot="aui_message-group" className="mb-14 flex flex-col gap-y-6 empty:hidden">
            <ThreadPrimitive.Messages>
              {() => <ThreadMessage task={task} embedWorkflowRecord={hasEmbeddedHistory} />}
            </ThreadPrimitive.Messages>
            {!hasEmbeddedHistory && <WorkflowRecord task={task} />}
          </div>

          <ThreadPrimitive.ViewportFooter
            className={cn(
              "aui-thread-viewport-footer bg-background flex flex-col gap-4 overflow-visible pb-4 md:pb-6",
              !isEmpty && "sticky bottom-0 mt-auto rounded-t-(--composer-radius)",
            )}
          >
            <ThreadScrollToBottom />
            <Composer />
            <AuiIf condition={(s) => isNewChatView(s) && s.composer.isEmpty}>
              <ThreadSuggestions />
            </AuiIf>
          </ThreadPrimitive.ViewportFooter>
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const ThreadMessage: FC<{
  task: CatalystTask | null;
  embedWorkflowRecord: boolean;
}> = ({ task, embedWorkflowRecord }) => {
  const role = useAuiState((s) => s.message.role);
  const isEditing = useAuiState((s) => s.message.composer.isEditing);

  if (isEditing) return <EditComposer />;
  if (role === "user") return <UserMessage />;
  return <AssistantMessage task={task} embedWorkflowRecord={embedWorkflowRecord} />;
};

const ThreadScrollToBottom: FC = () => {
  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <TooltipIconButton
        tooltip="滚动到底部"
        variant="outline"
        className="aui-thread-scroll-to-bottom dark:border-border dark:bg-background dark:hover:bg-accent absolute -top-12 z-10 self-center rounded-full p-4 disabled:invisible"
      >
        <ArrowDownIcon />
      </TooltipIconButton>
    </ThreadPrimitive.ScrollToBottom>
  );
};

const ThreadWelcome: FC = () => {
  return (
    <div className="aui-thread-welcome-root mb-6 flex flex-col items-center px-4 text-center">
      <h1 className="aui-thread-welcome-message-inner fade-in slide-in-from-bottom-1 animate-in fill-mode-both text-2xl font-semibold duration-200">
        今天想研究什么催化体系？
      </h1>
      <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
        输入电催化反应、材料或结构目标。当前以高熵合金工作流完整展示， 可创建真实 task_id、运行
        LangGraph 并在网页中完成阶段追踪与人工审查。
      </p>
    </div>
  );
};

const ThreadSuggestions: FC = () => {
  return (
    <div className="grid w-full max-w-2xl grid-cols-1 gap-2 px-4 md:grid-cols-3">
      <EntrySuggestion
        title="从研究目标开始"
        description="文献 → 候选 → 建模"
        prompt="请检索并审查可靠文献，设计用于电化学 CO2 还原的五元高熵合金催化剂，并对候选组合评分和排序。"
      />
      <EntrySuggestion
        title="直接构建五元组成"
        description="跳过文献，进入 direct C"
        prompt="我要构建 CuFeNiCoMn 五元高熵合金，生成三个 FCC 原子排布，并进行形成能和稳定性预筛。"
      />
      <EntrySuggestion
        title="使用已有结构"
        description="说明已有结构文件，并开始任务"
        prompt="我已有一个 bulk POSCAR，希望使用该结构继续执行形成能、稳定性、slab 和 DFT；请先告诉我当前网页入口如何提供这个结构文件。"
      />
    </div>
  );
};

type EntrySuggestionProps = {
  title: string;
  description: string;
  prompt: string;
};

const EntrySuggestion: FC<EntrySuggestionProps> = ({ title, description, prompt }) => {
  const composer = useComposerRuntime();
  const selectSuggestion = () => {
    composer.setText(prompt);
    // Let assistant-ui flush its controlled input before sending the preset.
    window.setTimeout(() => composer.send(), 0);
  };

  return (
    <Button
      type="button"
      variant="outline"
      onClick={selectSuggestion}
      className="h-auto min-h-20 w-full flex-col items-start gap-1 whitespace-normal p-3 text-left"
    >
      <span className="text-sm font-medium">{title}</span>
      <span className="text-xs leading-5 text-muted-foreground">{description}</span>
    </Button>
  );
};

const Composer: FC = () => {
  return (
    <ComposerPrimitive.Root className="aui-composer-root relative flex w-full flex-col">
      <ComposerPrimitive.AttachmentDropzone asChild>
        <div
          data-slot="aui_composer-shell"
          className="border-border/60 data-[dragging=true]:border-ring focus-within:border-border dark:border-muted-foreground/15 dark:focus-within:border-muted-foreground/30 flex w-full flex-col gap-2 rounded-(--composer-radius) border bg-(--composer-bg) p-(--composer-padding) shadow-[0_4px_16px_-8px_rgba(0,0,0,0.08),0_1px_2px_rgba(0,0,0,0.04)] transition-[border-color,box-shadow] focus-within:shadow-[0_6px_24px_-8px_rgba(0,0,0,0.12),0_1px_2px_rgba(0,0,0,0.05)] data-[dragging=true]:border-dashed data-[dragging=true]:bg-[color-mix(in_oklab,var(--color-accent)_50%,var(--color-background))] dark:shadow-none"
        >
          <ComposerAttachments />
          <ComposerTextInput />
          <ComposerAction />
        </div>
      </ComposerPrimitive.AttachmentDropzone>
    </ComposerPrimitive.Root>
  );
};

const ComposerTextInput: FC = () => {
  const { value, setText, send, isDisabled, canSend } = unstable_useComposerInput();
  const isComposing = useRef(false);

  const submitOnEnter = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      isComposing.current
    ) {
      return;
    }
    event.preventDefault();
    if (canSend) send();
  };

  return (
    <textarea
      value={value}
      onChange={(event) => setText(event.target.value)}
      onKeyDown={submitOnEnter}
      onCompositionStart={() => {
        isComposing.current = true;
      }}
      onCompositionEnd={(event) => {
        isComposing.current = false;
        setText(event.currentTarget.value);
      }}
      disabled={isDisabled}
      placeholder="描述电催化反应、材料目标或已有结构；如构建 CuFeNiCoMn 高熵合金并预筛"
      className="aui-composer-input placeholder:text-muted-foreground/80 max-h-32 min-h-10 w-full resize-none bg-transparent px-2.5 py-1 text-base outline-none"
      rows={1}
      autoFocus
      aria-label="消息输入框"
    />
  );
};

const ComposerAction: FC = () => {
  const { send, canSend } = unstable_useComposerInput();
  return (
    <div className="aui-composer-action-wrapper relative flex items-center justify-between">
      <ComposerAddAttachment />
      <div className="flex items-center gap-1.5">
        <AuiIf condition={(s) => s.thread.capabilities.dictation}>
          <AuiIf condition={(s) => s.composer.dictation == null}>
            <ComposerPrimitive.Dictate asChild>
              <TooltipIconButton
                tooltip="Voice input"
                side="bottom"
                type="button"
                variant="ghost"
                size="icon"
                className="aui-composer-dictate size-7 rounded-full"
                aria-label="Start voice input"
              >
                <MicIcon className="aui-composer-dictate-icon size-4" />
              </TooltipIconButton>
            </ComposerPrimitive.Dictate>
          </AuiIf>
          <AuiIf condition={(s) => s.composer.dictation != null}>
            <ComposerPrimitive.StopDictation asChild>
              <TooltipIconButton
                tooltip="Stop dictation"
                side="bottom"
                type="button"
                variant="ghost"
                size="icon"
                className="aui-composer-stop-dictation text-destructive size-7 rounded-full"
                aria-label="Stop voice input"
              >
                <SquareIcon className="aui-composer-stop-dictation-icon size-3.5 animate-pulse fill-current" />
              </TooltipIconButton>
            </ComposerPrimitive.StopDictation>
          </AuiIf>
        </AuiIf>
        <AuiIf condition={(s) => !s.thread.isRunning}>
          <TooltipIconButton
            tooltip={canSend ? "发送" : "请输入消息"}
            side="bottom"
            type="button"
            variant="default"
            size="icon"
            className="aui-composer-send size-7 rounded-full"
            aria-label="发送消息"
            disabled={!canSend}
            onClick={() => send()}
          >
            <ArrowUpIcon className="aui-composer-send-icon size-4.5" />
          </TooltipIconButton>
        </AuiIf>
        <AuiIf condition={(s) => s.thread.isRunning}>
          <ComposerPrimitive.Cancel asChild>
            <Button
              type="button"
              variant="default"
              size="icon"
              className="aui-composer-cancel size-7 rounded-full"
              aria-label="Stop generating"
            >
              <SquareIcon className="aui-composer-cancel-icon size-3.5 fill-current" />
            </Button>
          </ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </div>
  );
};

const MessageError: FC = () => {
  return (
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="aui-message-error-root border-destructive bg-destructive/10 text-destructive dark:bg-destructive/5 mt-2 rounded-md border p-3 text-sm dark:text-red-200">
        <ErrorPrimitive.Message className="aui-message-error-message line-clamp-2" />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
  );
};

const AssistantMessage: FC<{
  task: CatalystTask | null;
  embedWorkflowRecord: boolean;
}> = ({ task, embedWorkflowRecord }) => {
  const ACTION_BAR_PT = "pt-1.5";
  const ACTION_BAR_HEIGHT = `min-h-7.5 ${ACTION_BAR_PT}`;
  const consultationData = useAuiState((state) => {
    const part = state.message.parts.find(
      (item) => item.type === "data" && item.name === "consultation",
    ) as unknown as { data?: ConsultationData } | undefined;
    return part?.data ?? null;
  });
  const isConsultation = consultationData !== null;
  const consultations = task?.consultation_history ?? [];
  const consultationIndex = consultationData
    ? consultations.findIndex(
        (item) => item.consultation_id === consultationData.consultation.consultation_id,
      )
    : -1;
  const liveConsultation = consultationData
    ? consultationIndex >= 0
      ? consultations[consultationIndex]
      : consultationData.consultation
    : null;
  const nextConsultation =
    consultationIndex >= 0 ? consultations[consultationIndex + 1] : undefined;

  return (
    <>
      <MessagePrimitive.Root
        data-slot="aui_assistant-message-root"
        data-role="assistant"
        className={cn(
          "fade-in slide-in-from-bottom-1 animate-in relative -mb-7.5 pb-7.5 duration-150 [contain-intrinsic-size:auto_200px] [content-visibility:auto]",
          isConsultation && "rounded-md border border-sky-200 bg-sky-50/40 px-3 pt-3",
        )}
      >
        <div
          data-slot="aui_assistant-message-content"
          className="text-foreground px-2 leading-relaxed wrap-break-word"
        >
          <MessagePrimitive.Parts>
            {({ part }) => {
              if (part.type === "text") return <MarkdownText />;
              if (part.type === "data" && part.name === "task") {
                const data = part.data as TaskData;
                if (!embedWorkflowRecord || data.taskId !== task?.task_id) return null;
                const firstConsultation = task.consultation_history?.[0];
                return (
                  <WorkflowRecord
                    task={task}
                    includeConsultations={false}
                    beforeTime={firstConsultation?.created_at ?? ""}
                    showCompletion={!firstConsultation}
                  />
                );
              }
              if (part.type === "data" && part.name === "consultation") {
                const data = part.data as ConsultationData;
                const current = liveConsultation ?? data.consultation;
                return (
                  <ConsultationCard
                    consultation={current}
                    pending={
                      (consultationIndex >= 0
                        ? Boolean(task?.consultation_pending_continue)
                        : data.pending) && !current.continued
                    }
                    inline
                  />
                );
              }
              if (part.type === "data" && ["review", "stage"].includes(part.name)) return null;
              if (part.type === "tool-call") return part.toolUI ?? <ToolFallback {...part} />;
              return null;
            }}
          </MessagePrimitive.Parts>
          <AuiIf
            condition={(s) => s.message.status?.type === "running" && s.message.parts.length === 0}
          >
            <span
              data-slot="aui_assistant-message-indicator"
              className="animate-pulse font-sans"
              aria-label="Assistant is working"
            >
              {"●"}
            </span>
          </AuiIf>
          <MessageError />
        </div>

        <div
          data-slot="aui_assistant-message-footer"
          className={cn("ms-2 flex items-center", ACTION_BAR_HEIGHT)}
        >
          <BranchPicker />
          <AssistantActionBar />
        </div>
      </MessagePrimitive.Root>
      {liveConsultation && (
        <WorkflowRecord
          task={task}
          includeConsultations={false}
          afterTime={liveConsultation.created_at}
          beforeTime={nextConsultation?.created_at ?? ""}
          showCompletion={!nextConsultation}
        />
      )}
    </>
  );
};

const AssistantActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-assistant-action-bar-root text-muted-foreground animate-in fade-in col-start-3 row-start-2 -ms-1 flex gap-1 duration-200"
    >
      <ActionBarPrimitive.Copy asChild>
        <TooltipIconButton tooltip="Copy">
          <AuiIf condition={(s) => s.message.isCopied}>
            <CheckIcon className="animate-in zoom-in-50 fade-in duration-200 ease-out" />
          </AuiIf>
          <AuiIf condition={(s) => !s.message.isCopied}>
            <CopyIcon className="animate-in zoom-in-75 fade-in duration-150" />
          </AuiIf>
        </TooltipIconButton>
      </ActionBarPrimitive.Copy>
      <ActionBarPrimitive.Reload asChild>
        <TooltipIconButton tooltip="Refresh">
          <RefreshCwIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Reload>
      <ActionBarMorePrimitive.Root>
        <ActionBarMorePrimitive.Trigger asChild>
          <TooltipIconButton tooltip="More" className="data-[state=open]:bg-accent">
            <MoreHorizontalIcon />
          </TooltipIconButton>
        </ActionBarMorePrimitive.Trigger>
        <ActionBarMorePrimitive.Content
          side="bottom"
          align="start"
          sideOffset={6}
          className="aui-action-bar-more-content bg-popover/95 text-popover-foreground data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=closed]:animate-out data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 min-w-[8rem] overflow-hidden rounded-xl border p-1.5 shadow-lg backdrop-blur-sm"
        >
          <ActionBarPrimitive.ExportMarkdown asChild>
            <ActionBarMorePrimitive.Item className="aui-action-bar-more-item hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none select-none">
              <DownloadIcon className="size-4" />
              Export as Markdown
            </ActionBarMorePrimitive.Item>
          </ActionBarPrimitive.ExportMarkdown>
        </ActionBarMorePrimitive.Content>
      </ActionBarMorePrimitive.Root>
    </ActionBarPrimitive.Root>
  );
};

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root
      data-slot="aui_user-message-root"
      className="fade-in slide-in-from-bottom-1 animate-in grid auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 px-2 duration-150 [contain-intrinsic-size:auto_200px] [content-visibility:auto] [&:where(>*)]:col-start-2"
      data-role="user"
    >
      <UserMessageAttachments />

      <div className="aui-user-message-content-wrapper relative col-start-2 min-w-0">
        <div className="aui-user-message-content peer bg-muted text-foreground rounded-xl px-4 py-2 wrap-break-word empty:hidden">
          <MessagePrimitive.Parts />
        </div>
        <div className="aui-user-action-bar-wrapper absolute start-0 top-1/2 -translate-x-full -translate-y-1/2 pe-2 peer-empty:hidden rtl:translate-x-full">
          <UserActionBar />
        </div>
      </div>

      <BranchPicker
        data-slot="aui_user-branch-picker"
        className="col-span-full col-start-1 row-start-3 -me-1 justify-end"
      />
    </MessagePrimitive.Root>
  );
};

const UserActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-user-action-bar-root flex flex-col items-end"
    >
      <ActionBarPrimitive.Edit asChild>
        <TooltipIconButton tooltip="Edit" className="aui-user-action-edit">
          <PencilIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Edit>
    </ActionBarPrimitive.Root>
  );
};

const EditComposer: FC = () => {
  return (
    <MessagePrimitive.Root
      data-slot="aui_edit-composer-wrapper"
      className="flex flex-col px-2 [contain-intrinsic-size:auto_200px] [content-visibility:auto]"
    >
      <ComposerPrimitive.Root className="aui-edit-composer-root border-border/60 dark:border-muted-foreground/15 ms-auto flex w-full max-w-[85%] flex-col rounded-(--composer-radius) border bg-(--composer-bg) shadow-[0_4px_16px_-8px_rgba(0,0,0,0.08),0_1px_2px_rgba(0,0,0,0.04)] dark:shadow-none">
        <ComposerPrimitive.Input
          className="aui-edit-composer-input text-foreground min-h-14 w-full resize-none bg-transparent px-4 pt-3 pb-1 text-base outline-none"
          submitMode="enter"
          autoFocus
        />
        <div className="aui-edit-composer-footer mx-2.5 mb-2.5 flex items-center gap-1.5 self-end">
          <ComposerPrimitive.Cancel asChild>
            <Button variant="ghost" size="sm" className="h-8 rounded-full px-3.5">
              Cancel
            </Button>
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send asChild>
            <Button size="sm" className="h-8 rounded-full px-3.5">
              Update
            </Button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  );
};

const BranchPicker: FC<BranchPickerPrimitive.Root.Props> = ({ className, ...rest }) => {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch
      className={cn(
        "aui-branch-picker-root text-muted-foreground -ms-2 me-2 inline-flex items-center text-xs",
        className,
      )}
      {...rest}
    >
      <BranchPickerPrimitive.Previous asChild>
        <TooltipIconButton tooltip="Previous">
          <ChevronLeftIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Previous>
      <span className="aui-branch-picker-state font-medium">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next asChild>
        <TooltipIconButton tooltip="Next">
          <ChevronRightIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
};
