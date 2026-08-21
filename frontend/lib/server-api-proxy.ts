const API_BASE_URL =
  process.env.CATALYST_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export async function proxyCatalystRequest(path: string, init?: RequestInit) {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
      cache: "no-store",
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Response.json({ detail: `FastAPI 连接失败：${message}` }, { status: 502 });
  }
}
