import { NextResponse } from "next/server"
import { createClient } from "@/lib/supabase/server"

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: sessionId } = await params
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const body = await request.json()
  if (body?.language !== undefined) {
    if (body.language !== "fr" && body.language !== "en") {
      return NextResponse.json({ error: "Language must be fr or en" }, { status: 400 })
    }
    const { data: sessionRecord } = await supabase
      .from("sessions")
      .select("id, course_id")
      .eq("id", sessionId)
      .single()
    if (!sessionRecord) return NextResponse.json({ error: "Inquiry not found" }, { status: 404 })
    const { data: course } = await supabase.from("courses").select("id")
      .eq("id", sessionRecord.course_id).eq("user_id", user.id).single()
    if (!course) return NextResponse.json({ error: "Inquiry not found" }, { status: 404 })
    const { data: session, error } = await supabase.from("sessions")
      .update({ language: body.language, updated_at: new Date().toISOString() })
      .eq("id", sessionId).select().single()
    if (error) return NextResponse.json({ error: error.message }, { status: 500 })
    return NextResponse.json(session)
  }
  const { title } = body
  const normalizedTitle = typeof title === "string" ? title.trim() : ""

  if (!normalizedTitle) {
    return NextResponse.json({ error: "Title is required" }, { status: 400 })
  }
  if (normalizedTitle.length > 80) {
    return NextResponse.json({ error: "Title must be 80 characters or fewer" }, { status: 400 })
  }

  const { data: sessionRecord } = await supabase
    .from("sessions")
    .select("id, course_id")
    .eq("id", sessionId)
    .single()

  if (!sessionRecord) {
    return NextResponse.json({ error: "Inquiry not found" }, { status: 404 })
  }

  const { data: course } = await supabase
    .from("courses")
    .select("id")
    .eq("id", sessionRecord.course_id)
    .eq("user_id", user.id)
    .single()

  if (!course) {
    return NextResponse.json({ error: "Inquiry not found" }, { status: 404 })
  }

  const { data: session, error } = await supabase
    .from("sessions")
    .update({ title: normalizedTitle, updated_at: new Date().toISOString() })
    .eq("id", sessionId)
    .select()
    .single()

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  return NextResponse.json(session)
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: sessionId } = await params
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const { data: sessionRecord } = await supabase
    .from("sessions")
    .select("id, course_id")
    .eq("id", sessionId)
    .single()

  if (!sessionRecord) {
    return NextResponse.json({ error: "Inquiry not found" }, { status: 404 })
  }

  const { data: course } = await supabase
    .from("courses")
    .select("id")
    .eq("id", sessionRecord.course_id)
    .eq("user_id", user.id)
    .single()

  if (!course) {
    return NextResponse.json({ error: "Inquiry not found" }, { status: 404 })
  }

  const { error } = await supabase
    .from("sessions")
    .delete()
    .eq("id", sessionId)

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  return NextResponse.json({ success: true })
}
