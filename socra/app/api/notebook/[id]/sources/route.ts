import { NextResponse } from "next/server"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { notebookId } from "@/lib/notebook/schema"

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  if (!notebookId.test(id)) return NextResponse.json({ error: "Note not found." }, { status: 404 })
  const { data: note } = await client.from("notebook_notes").select("id")
    .eq("id", id).eq("user_id", user.id).maybeSingle()
  if (!note) return NextResponse.json({ error: "Note not found." }, { status: 404 })
  const service = await createServiceClient()
  const { data: sources, error } = await service.from("notebook_sources").select("id,kind,session_id,message_id,citations")
    .eq("note_id", note.id).eq("user_id", user.id).order("created_at")
  if (error) return NextResponse.json({ error: "Could not load sources." }, { status: 503 })
  const documentIds = [...new Set((sources ?? []).flatMap((source) => (Array.isArray(source.citations) ? source.citations : [])
    .flatMap((citation) => citation && typeof citation === "object" && !Array.isArray(citation) &&
      typeof citation.document_id === "string" && notebookId.test(citation.document_id) ? [citation.document_id] : [])))]
  const available = documentIds.length ? await client.from("documents").select("id").in("id", documentIds) : { data: [], error: null }
  if (available.error) return NextResponse.json({ error: "Could not verify PDF availability." }, { status: 503 })
  return NextResponse.json({ sources, availableDocuments: available.data?.map((document) => document.id) ?? [] })
}
