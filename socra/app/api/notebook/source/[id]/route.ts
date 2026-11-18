import { createClient, createServiceClient } from "@/lib/supabase/server"
import { notebookId } from "@/lib/notebook/schema"

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  if (!user) return new Response("Sign in to open the original response.", { status: 401 })
  const unavailable = () => new Response("The original Socra response is unavailable.", { status: 404 })
  if (!notebookId.test(id)) return unavailable()
  const service = await createServiceClient()
  const { data: source } = await service.from("notebook_sources").select("note_id,course_id,session_id,message_id")
    .eq("id", id).eq("user_id", user.id).maybeSingle()
  if (!source?.course_id || !source.session_id || !source.message_id) return unavailable()
  const [note, session, message] = await Promise.all([
    client.from("notebook_notes").select("id").eq("id", source.note_id).eq("user_id", user.id).maybeSingle(),
    client.from("sessions").select("id,courses!inner(user_id)").eq("id", source.session_id)
      .eq("course_id", source.course_id).eq("courses.user_id", user.id).maybeSingle(),
    client.from("messages").select("id").eq("id", source.message_id).eq("session_id", source.session_id).maybeSingle(),
  ])
  if (!note.data || !session.data || !message.data) return unavailable()
  const path = `/dashboard/course/${encodeURIComponent(source.course_id)}/inquiry/${encodeURIComponent(source.session_id)}`
  const query = new URLSearchParams({ message: source.message_id })
  return new Response(null, { status: 302, headers: { Location: `${path}?${query}`, "Cache-Control": "private, no-store" } })
}
