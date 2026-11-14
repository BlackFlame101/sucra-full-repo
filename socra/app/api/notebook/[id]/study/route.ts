import { NextResponse } from "next/server"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { notebookId } from "@/lib/notebook/schema"

const fail = (error: string, status: number) => NextResponse.json({ error }, { status })
type Params = { params: Promise<{ id: string }> }

async function access({ params }: Params) {
  const { id } = await params
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  if (!user) return fail("Sign in to study this note.", 401)
  if (!notebookId.test(id)) return fail("Note unavailable.", 404)
  const { data: note, error } = await client.from("notebook_notes").select("id,version,review_due")
    .eq("id", id).eq("user_id", user.id).maybeSingle()
  if (error) return fail("Could not load study settings.", 503)
  if (!note) return fail("Note unavailable.", 404)
  return { note, user, client }
}

export async function GET(_request: Request, params: Params) {
  const auth = await access(params)
  if (auth instanceof Response) return auth
  const service = await createServiceClient()
  const { data, error } = await service.from("notebook_flashcards").select("cards,note_version")
    .eq("note_id", auth.note.id).maybeSingle()
  return error ? fail("Could not load flashcards.", 503) : NextResponse.json({
    cards: data?.cards ?? [], stale: Boolean(data && data.note_version !== auth.note.version),
  })
}

export async function POST(_request: Request, params: Params) {
  const auth = await access(params)
  if (auth instanceof Response) return auth
  const service = await createServiceClient()
  const { data, error } = await service.rpc("open_notebook_thread", { owner: auth.user.id, note: auth.note.id })
  return error ? fail("Could not open this note’s inquiry.", 503)
    : data ? NextResponse.json(data) : fail("Note unavailable.", 404)
}

export async function PATCH(request: Request, params: Params) {
  const auth = await access(params)
  if (auth instanceof Response) return auth
  const body = await request.json().catch(() => null)
  const date = body?.review_due
  if (date !== null && (typeof date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      !Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date || date < "0001-01-01")) {
    return fail("Choose a valid review date.", 400)
  }
  const service = await createServiceClient()
  const { data, error } = await service.from("notebook_notes").update({ review_due: date })
    .eq("id", auth.note.id).eq("user_id", auth.user.id).select("review_due").maybeSingle()
  return error ? fail("Could not save the review date.", 503)
    : data ? NextResponse.json(data) : fail("Note unavailable.", 404)
}
