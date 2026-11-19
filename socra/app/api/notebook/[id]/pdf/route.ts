import { createClient } from "@/lib/supabase/server"
import { readNoteDocument } from "@/lib/notebook/document"
import { notebookPdf } from "@/lib/notebook/pdf"
import { notebookPdfFilename } from "@/lib/notebook/pdf-filename"
import { notebookId, validateNoteDocument } from "@/lib/notebook/schema"
import { notebookImageBucket, notebookImageLimit, ownsNotebookImagePath } from "@/lib/notebook/images"
import { prepareNotebookPdfImage } from "@/lib/server/notebook-image"

export const runtime = "nodejs"

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!notebookId.test(id)) return new Response("Note not found.", { status: 404 })
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  if (!user) return new Response("Sign in to save this note as a PDF.", { status: 401 })
  const { data: note, error } = await client.from("notebook_notes").select("title,content,content_json,source_type")
    .eq("id", id).eq("user_id", user.id).maybeSingle()
  if (error) return new Response("Could not open this note.", { status: 503 })
  if (!note) return new Response("Note not found.", { status: 404 })
  try {
    const doc = validateNoteDocument(readNoteDocument(note.content_json, note.content, note.source_type !== "manual"))
    const bytes = await notebookPdf(note.title, doc, new URL(request.url).origin, async (path) => {
      if (!ownsNotebookImagePath(path, user.id)) throw new Error("Invalid image owner.")
      const { data, error } = await client.storage.from(notebookImageBucket).download(path)
      if (error || !data || data.size > notebookImageLimit) throw new Error("Notebook image unavailable.")
      return prepareNotebookPdfImage(Buffer.from(await data.arrayBuffer()))
    })
    const filename = encodeURIComponent(notebookPdfFilename(note.title).toWellFormed())
      .replace(/['()*]/g, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`)
    return new Response(new Uint8Array(bytes), { headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="Notebook.pdf"; filename*=UTF-8''${filename}`,
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    } })
  } catch {
    return new Response("Could not export this note as a PDF.", { status: 422 })
  }
}
