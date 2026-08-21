import { proxyCatalystRequest } from "@/lib/server-api-proxy";
export async function GET(
  _request: Request,
  context: { params: Promise<{ taskId: string; fileId: string }> },
) {
  const { taskId, fileId } = await context.params;
  return proxyCatalystRequest(
    `/api/tasks/${encodeURIComponent(taskId)}/files/${encodeURIComponent(fileId)}/preview`,
  );
}
