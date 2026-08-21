import { proxyCatalystRequest } from "@/lib/server-api-proxy";
export async function GET(request: Request, context: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await context.params;
  const name = new URL(request.url).searchParams.get("name") ?? "OUTCAR";
  return proxyCatalystRequest(
    `/api/jobs/${encodeURIComponent(jobId)}/logs?name=${encodeURIComponent(name)}`,
  );
}
