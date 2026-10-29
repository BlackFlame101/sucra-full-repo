import { createClient } from "@/lib/supabase/server"
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
  if (!body || typeof body.title !== "string" || !body.title.trim() || typeof body.content !== "string") {
    return NextResponse.json({ error: "A title and note content are required." }, { status: 400 })
  }
  const { data: note, error } = await supabase.from("notebook_notes").update({
    title: body.title.trim().slice(0, 240),
    topic: typeof body.topic === "string" ? body.topic.trim().slice(0, 120) : "",
    content: body.content,
    updated_at: new Date().toISOString(),
  }).eq("id", id).eq("user_id", user.id).select().single()
  if (error) return NextResponse.json({ error: error.code === "PGRST116" ? "Note not found." : error.message }, { status: error.code === "PGRST116" ? 404 : 500 })
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
  const { error, count } = await supabase.from("notebook_notes").delete({ count: "exact" })
    .eq("id", id).eq("user_id", user.id)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  if (!count) return NextResponse.json({ error: "Note not found." }, { status: 404 })
  return NextResponse.json({ ok: true })
}
