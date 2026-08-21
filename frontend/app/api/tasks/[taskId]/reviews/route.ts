import { proxyCatalystRequest } from "@/lib/server-api-proxy";

export async function POST(request: Request, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  return proxyCatalystRequest(`/api/tasks/${encodeURIComponent(taskId)}/reviews`, {
    method: "POST",
    body: await request.text(),
  });
}
