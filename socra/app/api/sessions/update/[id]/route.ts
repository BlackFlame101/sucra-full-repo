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

  const { title } = await request.json()

  if (!title?.trim()) {
    return NextResponse.json({ error: "Title is required" }, { status: 400 })
  }

  const { data: session, error } = await supabase
    .from("sessions")
    .update({ title, updated_at: new Date().toISOString() })
    .eq("id", sessionId)
    .select()
    .single()

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  return NextResponse.json(session)
}
