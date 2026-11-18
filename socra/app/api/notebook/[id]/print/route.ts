import { randomBytes } from "node:crypto"
import { createClient } from "@/lib/supabase/server"
import { isEducationalDocument } from "@/lib/educational-document"
import { readNoteDocument } from "@/lib/notebook/document"
import { notebookId, validateNoteDocument } from "@/lib/notebook/schema"
import { notebookPrintHtml } from "@/lib/notebook/print"

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!notebookId.test(id)) return new Response("Note not found.", { status: 404 })
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  if (!user) return new Response("Sign in to export this note.", { status: 401 })
  const { data: note, error } = await client.from("notebook_notes").select("title,content,content_json,source_type,source_data")
    .eq("id", id).eq("user_id", user.id).maybeSingle()
  if (error) return new Response("Could not open this note.", { status: 503 })
  if (!note) return new Response("Note not found.", { status: 404 })
  const origin = (note.source_data as { explanation?: unknown } | null)?.explanation
  const french = isEducationalDocument(origin) && origin.intent.language === "French"
  const nonce = randomBytes(16).toString("base64")
  let html
  try {
    const doc = validateNoteDocument(readNoteDocument(note.content_json, note.content, note.source_type !== "manual"))
    html = notebookPrintHtml(note.title, doc, { french, nonce })
  } catch {
    return new Response("Could not render this note.", { status: 422 })
  }
  return new Response(html, { headers: {
    "Content-Type": "text/html; charset=utf-8", "Cache-Control": "private, no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-" + nonce +
      "'; frame-ancestors 'none'; base-uri 'none'",
    "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
  } })
}
