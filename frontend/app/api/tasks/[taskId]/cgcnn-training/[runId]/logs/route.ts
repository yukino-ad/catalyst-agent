import { proxyCatalystRequest } from "@/lib/server-api-proxy";

export async function GET(
  request: Request,
  context: { params: Promise<{ taskId: string; runId: string }> },
) {
  const { taskId, runId } = await context.params;
  const tail = new URL(request.url).searchParams.get("tail") ?? "400";
  return proxyCatalystRequest(
    `/api/tasks/${encodeURIComponent(taskId)}/cgcnn-training/${encodeURIComponent(runId)}/logs?tail=${encodeURIComponent(tail)}`,
  );
}
