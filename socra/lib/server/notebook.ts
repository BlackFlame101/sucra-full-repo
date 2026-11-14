import type { Json, TablesInsert } from "@/types/database"
import type { createClient } from "@/lib/supabase/server"
import { noteText } from "@/lib/notebook/document"
import { notebookId, validateNoteDocument } from "@/lib/notebook/schema"

export type NoteClient = Awaited<ReturnType<typeof createClient>>

export function editableNote(body: Record<string, unknown>) {
  if (typeof body.title !== "string" || !body.title.trim()) throw new Error("A note title is required.")
  const fields: Pick<TablesInsert<"notebook_notes">, "title" | "content" | "topic" | "content_json" | "tags" | "starred" | "course_id"> = {
    title: body.title.trim().slice(0, 240),
    topic: typeof body.topic === "string" ? body.topic.trim().slice(0, 120) : "",
  }
  if ("content_json" in body) {
    const doc = validateNoteDocument(body.content_json)
    fields.content_json = doc as Json
    fields.content = noteText(doc)
  } else if (typeof body.content === "string") fields.content = body.content
  else throw new Error("Note content is required.")
  if (fields.content.length > 250_000) throw new Error("The note is too long.")
  if ("tags" in body) {
    if (!Array.isArray(body.tags) || body.tags.length > 20 ||
        body.tags.some((tag) => typeof tag !== "string" || !tag.trim() || tag.trim().length > 40)) throw new Error("Use up to 20 tags of 40 characters each.")
    const tags = body.tags as string[]
    fields.tags = [...new Map(tags.map((tag) => [tag.trim().toLocaleLowerCase(), tag.trim()])).values()]
  }
  if ("starred" in body) {
    if (typeof body.starred !== "boolean") throw new Error("Invalid starred status.")
    fields.starred = body.starred
  }
  if ("course_id" in body) {
    if (body.course_id !== null && (typeof body.course_id !== "string" || !notebookId.test(body.course_id))) throw new Error("Invalid course.")
    fields.course_id = body.course_id
  }
  return fields
}

export async function ownsNoteCourse(client: NoteClient, owner: string, course: string) {
  const { data, error } = await client.from("courses").select("id").eq("id", course).eq("user_id", owner).maybeSingle()
  if (error) throw error
  return Boolean(data)
}
