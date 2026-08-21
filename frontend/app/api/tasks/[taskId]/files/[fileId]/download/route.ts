const API_BASE_URL =
  process.env.CATALYST_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
export async function GET(
  _request: Request,
  context: { params: Promise<{ taskId: string; fileId: string }> },
) {
  const { taskId, fileId } = await context.params;
  const response = await fetch(
    `${API_BASE_URL}/api/tasks/${encodeURIComponent(taskId)}/files/${encodeURIComponent(fileId)}/download`,
    { cache: "no-store" },
  );
  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream",
      "Content-Disposition": response.headers.get("Content-Disposition") ?? "attachment",
    },
  });
}
