import { createClient, createServiceClient } from "@/lib/supabase/server"
import { editableNote, ownsNoteCourse } from "@/lib/server/notebook"
import { notebookId } from "@/lib/notebook/schema"
import { NextResponse } from "next/server"

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  const body = await request.json().catch(() => null)
  if (!notebookId.test(id)) return NextResponse.json({ error: "Note not found." }, { status: 404 })
  if (!Number.isSafeInteger(body?.version) || body.version < 1 || body.version >= 2_147_483_647) {
    return NextResponse.json({ error: "A valid note version is required." }, { status: 400 })
  }
  let fields
  try { fields = editableNote(body, user.id) }
  catch (error) { return NextResponse.json({ error: (error as Error).message }, { status: 400 }) }
  try {
    if (fields.course_id && !await ownsNoteCourse(supabase, user.id, fields.course_id)) {
      return NextResponse.json({ error: "Course not found." }, { status: 404 })
    }
  } catch {
    return NextResponse.json({ error: "Could not check this course." }, { status: 503 })
  }
  const service = await createServiceClient()
  const { data: note, error } = await service.from("notebook_notes").update({
    ...fields, content_json: fields.content_json ?? null,
    version: body.version + 1, updated_at: new Date().toISOString(),
  }).eq("id", id).eq("user_id", user.id).eq("version", body.version).select().maybeSingle()
  if (error) return NextResponse.json({ error: "Could not save this note." }, { status: 500 })
  if (!note) {
    const { data: current, error: readError } = await supabase.from("notebook_notes").select("*")
      .eq("id", id).eq("user_id", user.id).maybeSingle()
    if (readError) return NextResponse.json({ error: "Could not check this note." }, { status: 503 })
    if (!current) return NextResponse.json({ error: "Note not found." }, { status: 404 })
    return NextResponse.json({ error: "This note changed elsewhere.", note: current }, { status: 409 })
  }
  return NextResponse.json(note)
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  if (!notebookId.test(id)) return NextResponse.json({ error: "Note not found." }, { status: 404 })
  const { error, count } = await supabase.from("notebook_notes").delete({ count: "exact" })
    .eq("id", id).eq("user_id", user.id)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  if (!count) return NextResponse.json({ error: "Note not found." }, { status: 404 })
  return NextResponse.json({ ok: true })
}
