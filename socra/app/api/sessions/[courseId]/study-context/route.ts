import { createClient } from "@/lib/supabase/server"
import { uuidPattern } from "@/lib/server/document-jobs"

export async function GET(_request: Request, { params }: { params: Promise<{ courseId: string }> }) {
  const { courseId: sessionId } = await params
  if (!uuidPattern.test(sessionId)) return Response.json({ error: "Inquiry not found." }, { status: 404 })
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  if (!user) return Response.json({ error: "Sign in to view course context." }, { status: 401 })
  const { data: session } = await client.from("sessions").select("id,courses!inner(user_id)")
    .eq("id", sessionId).eq("courses.user_id", user.id).maybeSingle()
  if (!session) return Response.json({ error: "Inquiry not found." }, { status: 404 })
  const { data, error } = await client.from("key_terms").select("term").eq("session_id", session.id)
    .order("created_at", { ascending: false }).limit(8)
  if (error) return Response.json({ error: "Could not load study context." }, { status: 503 })
  return Response.json({ key_terms: [...new Set(data.map(({ term }) => term))] }, { headers: { "Cache-Control": "private, no-store" } })
}
