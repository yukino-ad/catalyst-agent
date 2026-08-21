import { proxyCatalystRequest } from "@/lib/server-api-proxy";

const API_BASE_URL =
  process.env.CATALYST_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export async function POST(request: Request) {
  if (new URL(request.url).searchParams.get("stream") === "1") {
    try {
      const response = await fetch(`${API_BASE_URL}/api/conversations/respond/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: await request.text(),
        cache: "no-store",
        signal: request.signal,
      });
      return new Response(response.body, {
        status: response.status,
        headers: {
          "Content-Type": "application/x-ndjson; charset=utf-8",
          "Cache-Control": "no-cache, no-transform",
          "X-Accel-Buffering": "no",
        },
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return Response.json({ detail: `FastAPI 连接失败：${message}` }, { status: 502 });
    }
  }
  return proxyCatalystRequest("/api/conversations/respond", {
    method: "POST",
    body: await request.text(),
  });
}
