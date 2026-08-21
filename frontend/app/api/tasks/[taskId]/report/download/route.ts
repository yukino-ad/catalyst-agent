const API_BASE_URL =
  process.env.CATALYST_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export async function GET(request: Request, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  const format = new URL(request.url).searchParams.get("format") ?? "html";
  const response = await fetch(
    `${API_BASE_URL}/api/tasks/${encodeURIComponent(taskId)}/report/download?format=${encodeURIComponent(format)}`,
    { cache: "no-store" },
  );
  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream",
      "Content-Disposition":
        format === "html"
          ? "inline"
          : (response.headers.get("Content-Disposition") ?? "attachment"),
    },
  });
}
