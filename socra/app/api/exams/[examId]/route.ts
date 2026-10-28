import { proxyExamRequest } from "@/lib/server/exam-proxy"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ examId: string }> },
) {
  const { examId } = await params
  return proxyExamRequest(`/exams/${encodeURIComponent(examId)}`, "GET")
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ examId: string }> },
) {
  const { examId } = await params
  const body = await request.json().catch(() => ({}))
  return proxyExamRequest(`/exams/${encodeURIComponent(examId)}/submit`, "POST", body)
}
