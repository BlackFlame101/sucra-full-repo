import { createClient, createServiceClient } from "@/lib/supabase/server"
import { explanationNoteText } from "@/lib/ai/explanation-note"
import { readSavedExplanation } from "@/lib/server/saved-explanation"
import { editableNote } from "@/lib/server/notebook"
import { educationalCitations, isEducationalDocument } from "@/lib/educational-document"
import { educationalNote, noteText } from "@/lib/notebook/document"
import { validateNoteDocument } from "@/lib/notebook/schema"
import type { Json } from "@/types/database"
import { NextResponse } from "next/server"

const sourceTypes = ["manual", "explanation", "exercise"] as const

export async function GET(request: Request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  if (new URL(request.url).searchParams.get("view") === "picker") {
    const { data, error } = await supabase.from("notebook_notes").select("id,title,course_id")
      .eq("user_id", user.id).order("updated_at", { ascending: false })
    return error ? NextResponse.json({ error: "Could not load notes." }, { status: 500 })
      : NextResponse.json({ notes: data })
  }

  const [notesResult, coursesResult] = await Promise.all([
    supabase.from("notebook_notes").select("*").eq("user_id", user.id)
      .order("updated_at", { ascending: false }),
    supabase.from("courses").select("id,name").eq("user_id", user.id)
      .eq("notebook_private", false)
      .order("name", { ascending: true }),
  ])
  if (notesResult.error) return NextResponse.json({ error: notesResult.error.message }, { status: 500 })
  if (coursesResult.error) return NextResponse.json({ error: coursesResult.error.message }, { status: 500 })
  const documentIds = [...new Set((notesResult.data ?? []).map((note) => note.source_document_id).filter((id): id is string => Boolean(id)))]
  const documentsResult = documentIds.length
    ? await supabase.from("documents").select("id,filename").in("id", documentIds)
    : { data: [], error: null }
  if (documentsResult.error) return NextResponse.json({ error: documentsResult.error.message }, { status: 500 })
  const courseNames = new Map((coursesResult.data ?? []).map((course) => [course.id, course.name]))
  const documentNames = new Map((documentsResult.data ?? []).map((document) => [document.id, document.filename]))
  return NextResponse.json({
    notes: (notesResult.data ?? []).map((note) => ({
      ...note,
      course_name: note.course_id ? courseNames.get(note.course_id) ?? "Course" : "Personal",
      source_filename: note.source_document_id ? documentNames.get(note.source_document_id) : undefined,
    })),
    courses: coursesResult.data ?? [],
  })
}

export async function POST(request: Request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  const body = await request.json().catch(() => null)
  let editable
  try { editable = editableNote(body ?? {}) }
  catch (error) { return NextResponse.json({ error: (error as Error).message }, { status: 400 }) }
  const sourceType = sourceTypes.includes(body.source_type) ? body.source_type : "manual"
  if (sourceType === "exercise") return NextResponse.json({ error: "Save exercise feedback from its inquiry." }, { status: 400 })
  let courseId = editable.course_id ?? null
  if (courseId) {
    const { data: course } = await supabase.from("courses").select("id")
      .eq("id", courseId).eq("user_id", user.id).single()
    if (!course) return NextResponse.json({ error: "Course not found." }, { status: 404 })
  }
  if (sourceType === "explanation") {
    let explanation
    if (typeof body.library_item_id === "string") {
      const { data: item } = await supabase.from("library_items").select("content,course_id")
        .eq("id", body.library_item_id).eq("user_id", user.id).eq("item_type", "explanation").maybeSingle()
      const saved = item?.content as { explanation?: Awaited<ReturnType<typeof readSavedExplanation>> } | null
      if (item && item.course_id === courseId) {
        explanation = saved?.explanation
        const source = item.content as { session_id?: string; message_id?: string } | null
        body.source_data = { session_id: source?.session_id, message_id: source?.message_id }
      }
    } else {
      explanation = await readSavedExplanation(supabase, user.id, courseId, body.source_data)
    }
    if (!explanation) return NextResponse.json({ error: "A completed or saved explanation is required." }, { status: 404 })
    if (isEducationalDocument(explanation)) {
      try {
        const doc = validateNoteDocument(educationalNote(explanation))
        editable.content_json = doc as Json
        editable.content = noteText(doc)
      } catch {
        return NextResponse.json({ error: "Could not read the saved educational document." }, { status: 422 })
      }
    } else {
      editable.content = explanationNoteText(explanation)
      delete editable.content_json
    }
    body.source_data = { ...body.source_data, explanation }
    const citations = isEducationalDocument(explanation) ? educationalCitations(explanation) : explanation.citations
    body.source_document_id = citations[0]?.document_id
    body.source_page = citations[0]?.page_number
  }
  let sourceDocumentId = typeof body.source_document_id === "string" ? body.source_document_id : null
  if (sourceDocumentId) {
    const { data: document } = await supabase.from("documents").select("id,course_id")
      .eq("id", sourceDocumentId).single()
    if (!document && sourceType === "explanation") sourceDocumentId = null
    else if (!document) return NextResponse.json({ error: "Source document not found." }, { status: 404 })
    if (document) {
      if (courseId && document.course_id !== courseId) return NextResponse.json({ error: "Source document does not belong to this course." }, { status: 400 })
      const { data: documentCourse } = await supabase.from("courses").select("id")
        .eq("id", document.course_id).eq("user_id", user.id).single()
      if (!documentCourse) return NextResponse.json({ error: "Source document not found." }, { status: 404 })
      courseId = document.course_id
    }
  }
  const { data: note, error } = await (await createServiceClient()).from("notebook_notes").insert({
    ...editable,
    user_id: user.id,
    course_id: courseId,
    source_type: sourceType,
    source_data: sourceType === "explanation" ? {
      session_id: body.source_data?.session_id,
      message_id: body.source_data?.message_id,
      explanation: body.source_data?.explanation,
      ...(isEducationalDocument(body.source_data?.explanation) ? { initial_note_version: 1 } : {}),
    } : {},
    source_document_id: sourceDocumentId,
    source_page: sourceDocumentId && Number.isInteger(body.source_page) && body.source_page > 0 ? body.source_page : null,
  }).select().single()
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(note, { status: 201 })
}
