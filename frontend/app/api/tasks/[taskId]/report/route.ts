import { proxyCatalystRequest } from "@/lib/server-api-proxy";

export async function GET(_request: Request, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  return proxyCatalystRequest(`/api/tasks/${encodeURIComponent(taskId)}/report`);
}

export async function POST(_request: Request, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  return proxyCatalystRequest(`/api/tasks/${encodeURIComponent(taskId)}/report`, {
    method: "POST",
  });
}
