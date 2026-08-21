import { proxyCatalystRequest } from "@/lib/server-api-proxy";

export async function POST(request: Request) {
  return proxyCatalystRequest("/api/literature/translations", {
    method: "POST",
    body: await request.text(),
  });
}
