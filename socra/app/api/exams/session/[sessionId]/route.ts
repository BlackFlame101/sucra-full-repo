import { proxyExamRequest } from "@/lib/server/exam-proxy"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params
  return proxyExamRequest(`/exams/session/${encodeURIComponent(sessionId)}`, "GET")
}
