import { proxyCatalystRequest } from "@/lib/server-api-proxy";
export async function GET(
  _request: Request,
  context: { params: Promise<{ taskId: string; structureId: string }> },
) {
  const { taskId, structureId } = await context.params;
  return proxyCatalystRequest(
    `/api/tasks/${encodeURIComponent(taskId)}/structures/${encodeURIComponent(structureId)}`,
  );
}
