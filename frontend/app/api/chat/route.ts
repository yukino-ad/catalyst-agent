import { createUIMessageStream, createUIMessageStreamResponse } from "ai";
import { createCatalystTask, getCatalystTask, streamCatalystAssistant } from "@/lib/catalyst-api";
import { classifyConversationEntry } from "@/lib/conversation-entry";
import type { CatalystUIMessage } from "@/lib/review-types";

export const maxDuration = 180;

export async function POST(request: Request) {
  const payload = (await request.json()) as { messages?: CatalystUIMessage[] };
  const question = lastUserText(payload.messages ?? []);
  if (!question) {
    return Response.json({ error: "没有找到用户输入。" }, { status: 400 });
  }
  const entry = classifyConversationEntry(question);
  const taskId = latestTaskId(payload.messages ?? []);

  const stream = createUIMessageStream<CatalystUIMessage>({
    originalMessages: payload.messages,
    execute: async ({ writer }) => {
      const textId = `task-${Date.now()}`;
      const streamText = (text: string, speed: StreamSpeed = "normal") =>
        writeTextGradually(
          (delta) => writer.write({ type: "text-delta", id: textId, delta }),
          text,
          speed,
        );
      writer.write({ type: "text-start", id: textId });
      try {
        if (!taskId && !entry.createTask) {
          await streamText("正在理解你的问题...\n\n", "status");
          await streamText(entry.response ?? "请告诉我你想完成的科研任务。");
          return;
        }

        await streamText(
          taskId ? "正在读取当前任务上下文...\n\n" : "正在识别科研意图...\n\n",
          "status",
        );
        let streamedAnswer = false;
        const consultation = await streamCatalystAssistant(question, taskId, (delta) => {
          streamedAnswer = true;
          writer.write({ type: "text-delta", id: textId, delta });
        });
        if (taskId || !consultation.create_workflow) {
          if (!streamedAnswer) {
            await streamText(consultation.answer || "已记录本次科研咨询。", "normal");
          }
          if (consultation.requires_continue_confirmation) {
            if (!consultation.consultation_id) {
              throw new Error("咨询完成后缺少 consultation_id，工作流保持暂停。");
            }
            writer.write({
              type: "data-consultation",
              id: `consultation-${consultation.consultation_id}`,
              data: {
                consultation,
                pending: true,
              },
            });
          }
          return;
        }

        await streamText("已识别为工作流任务，正在创建后台任务...\n\n", "status");
        const created = await createCatalystTask(question);
        const initialTask = await getCatalystTask(created.task_id);
        writer.write({
          type: "data-task",
          id: `task-ref-${created.task_id}`,
          data: { taskId: created.task_id, task: initialTask },
        });
        await streamText(
          `任务已创建。\n\n- task_id：\`${created.task_id}\`\n- 状态：已进入后台队列\n\nA1-A4、B1-B6、C1-C12.7 的阶段结果、人工审查和后续咨询会持续追加在本聊天台。`,
          "fast",
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        await streamText(`\n\n任务运行失败：${message}`);
      } finally {
        writer.write({ type: "text-end", id: textId });
      }
    },
  });

  return createUIMessageStreamResponse({ stream });
}

function latestTaskId(messages: CatalystUIMessage[]): string {
  for (const message of [...messages].reverse()) {
    for (const part of [...message.parts].reverse()) {
      const value = part as unknown as {
        type?: string;
        name?: string;
        data?: { taskId?: string };
      };
      if (
        (value.type === "data-task" || (value.type === "data" && value.name === "task")) &&
        value.data?.taskId
      ) {
        return value.data.taskId;
      }
    }
  }
  return "";
}

function lastUserText(messages: CatalystUIMessage[]): string {
  const message = [...messages].reverse().find((item) => item.role === "user");
  if (!message) return "";
  return message.parts
    .filter(
      (part): part is Extract<(typeof message.parts)[number], { type: "text" }> =>
        part.type === "text",
    )
    .map((part) => part.text)
    .join("\n")
    .trim();
}

function delay(milliseconds: number) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

type StreamSpeed = "normal" | "fast" | "status";

const STREAM_SETTINGS: Record<StreamSpeed, { chunkSize: number; delayMs: number }> = {
  normal: { chunkSize: 3, delayMs: 24 },
  fast: { chunkSize: 6, delayMs: 14 },
  status: { chunkSize: 4, delayMs: 32 },
};

async function writeTextGradually(
  write: (delta: string) => void,
  text: string,
  speed: StreamSpeed,
) {
  const { chunkSize, delayMs } = STREAM_SETTINGS[speed];
  for (let index = 0; index < text.length; index += chunkSize) {
    write(text.slice(index, index + chunkSize));
    await delay(delayMs);
  }
}
