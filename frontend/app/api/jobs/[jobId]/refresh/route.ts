import { proxyCatalystRequest } from "@/lib/server-api-proxy";
export async function POST(_request: Request, context: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await context.params;
  return proxyCatalystRequest(`/api/jobs/${encodeURIComponent(jobId)}/refresh`, { method: "POST" });
}
