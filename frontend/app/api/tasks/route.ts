import { proxyCatalystRequest } from "@/lib/server-api-proxy";

export async function GET() {
  return proxyCatalystRequest("/api/tasks");
}
