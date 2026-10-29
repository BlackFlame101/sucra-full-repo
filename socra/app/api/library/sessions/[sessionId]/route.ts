import { NextResponse } from "next/server"
import { createClient } from "@/lib/supabase/server"
import { proxyExamRequest } from "@/lib/server/exam-proxy"
import type { Json } from "@/types"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { data: session } = await supabase.from("sessions")
    .select("id,course_id")
    .eq("id", sessionId)
    .single()
  if (!session) return NextResponse.json({ error: "Session not found." }, { status: 404 })

  const { data: course } = await supabase.from("courses")
    .select("id")
    .eq("id", session.course_id)
    .eq("user_id", user.id)
    .single()
  if (!course) return NextResponse.json({ error: "Session not found." }, { status: 404 })

  const [inquiryResult, examResult] = await Promise.all([
    supabase.from("library_items").select("id").eq("user_id", user.id)
      .eq("course_id", course.id).eq("item_type", "inquiry")
      .contains("content", { snapshot: { session_id: session.id, kind: "inquiry" } }).maybeSingle(),
    supabase.from("library_items").select("id").eq("user_id", user.id)
      .eq("course_id", course.id).eq("item_type", "exam")
      .contains("content", { snapshot: { session_id: session.id, kind: "exam" } }).maybeSingle(),
  ])
  if (inquiryResult.error) return NextResponse.json({ error: inquiryResult.error.message }, { status: 500 })
  if (examResult.error) return NextResponse.json({ error: examResult.error.message }, { status: 500 })
  return NextResponse.json({ saved: Boolean(inquiryResult.data || examResult.data), item_type: examResult.data ? "exam" : inquiryResult.data ? "inquiry" : null })
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await request.json().catch(() => null)
  const itemType = body?.item_type
  if (itemType !== "inquiry" && itemType !== "exam") {
    return NextResponse.json({ error: "Choose an inquiry or exam to save." }, { status: 400 })
  }
  const kind = itemType as "inquiry" | "exam"

  const { data: session } = await supabase.from("sessions")
    .select("id,title,course_id")
    .eq("id", sessionId)
    .single()
  if (!session) return NextResponse.json({ error: "Session not found." }, { status: 404 })

  const { data: course } = await supabase.from("courses")
    .select("id")
    .eq("id", session.course_id)
    .eq("user_id", user.id)
    .single()
  if (!course) return NextResponse.json({ error: "Session not found." }, { status: 404 })

  const snapshotFilter: Json = { snapshot: { session_id: session.id, kind } }
  const { data: existing } = await supabase.from("library_items")
    .select("id")
    .eq("user_id", user.id)
    .eq("course_id", course.id)
    .eq("item_type", kind)
    .contains("content", snapshotFilter)
    .maybeSingle()
  if (existing) return NextResponse.json({ id: existing.id, already_saved: true })

  const { data: messages, error: messagesError } = await supabase.from("messages")
    .select("id,role,content,metadata,created_at")
    .eq("session_id", session.id)
    .order("created_at", { ascending: true })
  if (messagesError) return NextResponse.json({ error: messagesError.message }, { status: 500 })

  let exam: unknown
  if (itemType === "exam") {
    const examResponse = await proxyExamRequest(
      `/exams/session/${encodeURIComponent(session.id)}`,
      "GET",
      undefined,
      8000,
    )
    if (!examResponse.ok) {
      const payload = await examResponse.json().catch(() => null)
      return NextResponse.json({ error: payload?.detail || "Could not retrieve the exam to save it." }, { status: examResponse.status })
    }
    exam = await examResponse.json()
  }

  const title = (session.title?.trim() || (kind === "exam" ? "Mixed Course Exam" : "Saved inquiry")).slice(0, 240)
  const { data: item, error } = await supabase.from("library_items").insert({
    user_id: user.id,
    course_id: course.id,
    item_type: kind,
    title,
    content: {
      snapshot: {
        kind,
        session_id: session.id,
        messages: messages ?? [],
        ...(kind === "exam" ? { exam } : {}),
      },
    } as Json,
  }).select("id").single()

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(item, { status: 201 })
}
