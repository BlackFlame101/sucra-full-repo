import { proxyExamRequest } from "@/lib/server/exam-proxy"

export async function POST(request: Request) {
  const body = await request.json().catch(() => null)
  if (!body || typeof body !== "object") {
    return Response.json({ detail: "Invalid exam request." }, { status: 400 })
  }
  return proxyExamRequest("/exams/start", "POST", body)
}
