import { proxyExamRequest } from "@/lib/server/exam-proxy"

export async function POST(
  request: Request,
  { params }: { params: Promise<{ examId: string }> },
) {
  const { examId } = await params
  const body = await request.json().catch(() => null)
  if (!body || typeof body !== "object") {
    return Response.json({ detail: "Invalid exam answer." }, { status: 400 })
  }
  return proxyExamRequest(`/exams/${encodeURIComponent(examId)}/answer`, "POST", body)
}
