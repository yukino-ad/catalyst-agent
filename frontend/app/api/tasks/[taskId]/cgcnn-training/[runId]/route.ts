import { proxyCatalystRequest } from "@/lib/server-api-proxy";

export async function GET(
  _request: Request,
  context: { params: Promise<{ taskId: string; runId: string }> },
) {
  const { taskId, runId } = await context.params;
  return proxyCatalystRequest(
    `/api/tasks/${encodeURIComponent(taskId)}/cgcnn-training/${encodeURIComponent(runId)}`,
  );
}
