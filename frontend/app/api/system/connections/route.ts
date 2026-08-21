import { proxyCatalystRequest } from "@/lib/server-api-proxy";

export async function GET() {
  return proxyCatalystRequest("/api/system/connections");
}

export async function POST() {
  return proxyCatalystRequest("/api/system/connections/check", { method: "POST" });
}
