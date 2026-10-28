import { NextResponse } from "next/server"
import { createClient } from "@/lib/supabase/server"
import { proxyExamRequest } from "@/lib/server/exam-proxy"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ courseId: string }> }
) {
  const { courseId } = await params
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const { data: sessions, error } = await supabase
    .from("sessions")
    .select("*")
    .eq("course_id", courseId)
    .order("updated_at", { ascending: false })

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  const examsResponse = await proxyExamRequest(
    `/exams/course/${encodeURIComponent(courseId)}/sessions`,
    "GET",
  )
  const examPayload: unknown = examsResponse.ok ? await examsResponse.json() : []
  const exams = Array.isArray(examPayload) ? examPayload as Array<{
    id: string
    session_id: string
    status: "in_progress" | "completed"
  }> : []
  const examBySession = new Map(exams.map((exam) => [exam.session_id, exam]))
  return NextResponse.json((sessions ?? []).map((session) => {
    const exam = examBySession.get(session.id)
    return exam
      ? { ...session, exam_id: exam.id, exam_status: exam.status }
      : session
  }))
}
