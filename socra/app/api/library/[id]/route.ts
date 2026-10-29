import { createClient } from "@/lib/supabase/server"
import { NextResponse } from "next/server"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { data: item, error } = await supabase.from("library_items").select("*")
    .eq("id", id).eq("user_id", user.id).single()
  if (error || !item) return NextResponse.json({ error: "Saved item not found." }, { status: 404 })

  const { data: course } = await supabase.from("courses").select("name")
    .eq("id", item.course_id).eq("user_id", user.id).single()
  const snapshot = (item.content as { snapshot?: { session_id?: unknown } }).snapshot
  const snapshotSessionId = typeof snapshot?.session_id === "string" ? snapshot.session_id : null
  const { data: originalSession } = snapshotSessionId
    ? await supabase.from("sessions").select("id").eq("id", snapshotSessionId).eq("course_id", item.course_id).maybeSingle()
    : { data: null }
  return NextResponse.json({
    ...item,
    course_name: course?.name ?? "Course",
    original_session_id: originalSession?.id ?? null,
  })
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  const { error, count } = await supabase.from("library_items").delete({ count: "exact" })
    .eq("id", id).eq("user_id", user.id)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  if (!count) return NextResponse.json({ error: "Saved item not found." }, { status: 404 })
  return NextResponse.json({ ok: true })
}
