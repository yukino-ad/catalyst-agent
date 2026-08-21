import { proxyCatalystRequest } from "@/lib/server-api-proxy";

type Context = { params: Promise<{ taskId: string }> };

export async function GET(_request: Request, context: Context) {
  const { taskId } = await context.params;
  return proxyCatalystRequest(`/api/tasks/${encodeURIComponent(taskId)}/cgcnn-training`);
}

export async function POST(request: Request, context: Context) {
  const { taskId } = await context.params;
  return proxyCatalystRequest(`/api/tasks/${encodeURIComponent(taskId)}/cgcnn-training`, {
    method: "POST",
    body: await request.text(),
  });
}
