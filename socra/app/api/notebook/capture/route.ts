import { createHash } from "node:crypto"
import type { JSONContent } from "@tiptap/react"
import { NextResponse } from "next/server"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { explanationNoteText } from "@/lib/ai/explanation-note"
import { markdownNote, noteText, readNoteDocument, selectNoteText, type NoteDocument } from "@/lib/notebook/document"
import { notebookId, validateNoteDocument } from "@/lib/notebook/schema"
import type { ExerciseCitation, PublicCorrection, PublicExplanation, SuggestedReadingItem } from "@/lib/socra-ws"
import type { Json } from "@/types/database"

const fail = (error: string, status: number) => NextResponse.json({ error }, { status })

function qcmPageLinks(doc: NoteDocument): ExerciseCitation[] {
  const pages = new Map<string, ExerciseCitation>()
  function visit(node: JSONContent) {
    for (const mark of node.marks ?? []) {
      if (mark.type !== "link") continue
      const match = /^\/api\/documents\/view\/([\da-f-]+)\?page=([1-9]\d*)#page=\2$/i.exec(mark.attrs?.href ?? "")
      if (!match || !notebookId.test(match[1]) || !Number.isSafeInteger(Number(match[2]))) {
        throw new Error("Invalid QCM page link.")
      }
      const document_id = match[1].toLowerCase()
      const page_number = Number(match[2])
      pages.set(`${document_id}:${page_number}`, { document_id, page_number, filename: "Course PDF", excerpt: "" })
    }
    node.content?.forEach(visit)
  }
  visit(doc)
  if (!pages.size) throw new Error("Missing QCM page links.")
  return [...pages.values()]
}

export async function POST(request: Request) {
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  if (!user) return fail("Unauthorized", 401)
  const body = await request.json().catch(() => null)
  if (!body || ![body.course_id, body.session_id, body.message_id, body.request_id].every(
    (value) => typeof value === "string" && notebookId.test(value)) ||
    (body.note_id != null && (typeof body.note_id !== "string" || !notebookId.test(body.note_id))) ||
    (body.selection != null && (typeof body.selection !== "string" || body.selection.length > 12_000))) return fail("Invalid response or note.", 400)

  const { data: session } = await client.from("sessions").select("id,courses!inner(user_id)")
    .eq("id", body.session_id).eq("course_id", body.course_id).eq("courses.user_id", user.id).maybeSingle()
  if (!session) return fail("Original inquiry unavailable.", 404)
  const { data: message } = await client.from("messages").select("content,metadata")
    .eq("id", body.message_id).eq("session_id", session.id).eq("role", "assistant").maybeSingle()
  if (!message) return fail("Wait for the response to finish saving, then try again.", 404)
  const metadata = (message.metadata ?? {}) as {
    explanation?: PublicExplanation; correction?: PublicCorrection; exercise?: unknown; exercise_id?: string
    qcm_status?: "unreviewed" | "partial" | "failed"
    course_lesson_status?: "unreviewed" | "partial" | "failed"
    course_context?: { suggested_readings?: SuggestedReadingItem[] }
  }
  if (metadata.qcm_status === "failed") return fail("This QCM has no answer to save.", 422)
  if (metadata.course_lesson_status === "failed") return fail("This lesson has no answer to save.", 422)
  const qcm = metadata.qcm_status === "unreviewed" || metadata.qcm_status === "partial"
  const sourcedMarkdown = qcm || Boolean(metadata.course_lesson_status)
  const explanation = qcm ? undefined : metadata.explanation
  const correction = qcm ? undefined : metadata.correction
  const kind = sourcedMarkdown || explanation ? "explanation" : correction ? "exercise" : "tutor"
  if (metadata.exercise && !correction) return fail("Save the feedback after answering the exercise.", 400)
  let content = message.content
  let doc: NoteDocument | undefined
  const explanationCitations = explanation && [
    ...(explanation.citations ?? []), ...(explanation.sections ?? []).flatMap((section) => section.citations ?? []),
  ]
  let citations: ExerciseCitation[] = explanationCitations ?? correction?.citations ??
    (metadata.course_context?.suggested_readings ?? []).flatMap((reading) => reading.document_id
      ? [{ ...reading, document_id: reading.document_id, filename: reading.filename ?? "Course PDF" }] : [])
  if (sourcedMarkdown) {
    // The persisted Markdown is the same final answer displayed in chat.
    try {
      doc = validateNoteDocument(markdownNote(message.content))
      citations = qcmPageLinks(doc)
    } catch {
      return fail("This response could not be converted into a note with its source pages.", 422)
    }
  }
  const service = await createServiceClient()
  if (correction) {
    content = ["## Feedback", correction.overall_feedback,
      ...correction.criterion_feedback.flatMap((item) => [`### ${item.criterion}`, `${item.awarded_points} / ${item.possible_points}`, item.feedback]),
      "## Next step", correction.next_step].join("\n\n")
    if (metadata.exercise_id) {
      const { data: revealed, error } = await service.from("exercise_attempts").select("id")
        .eq("exercise_id", metadata.exercise_id).eq("session_id", session.id).eq("user_id", user.id)
        .eq("solution_revealed", true).limit(1).maybeSingle()
      if (error) return fail("Could not verify the revealed solution.", 503)
      if (revealed) {
        const { data: exercise, error } = await service.from("exercises").select("expected_answer,common_mistakes,exercise_data,exercise_type")
          .eq("id", metadata.exercise_id).eq("session_id", session.id).eq("course_id", body.course_id).maybeSingle()
        if (error) return fail("Could not load the revealed solution.", 503)
        const options = exercise?.exercise_data as { code_expected_answers?: string | string[]; code_task_mode?: string; starter_code?: string } | null
        const completion = exercise?.exercise_type === "code" &&
          (options?.code_task_mode === "completion" || (!options?.code_task_mode && options?.starter_code?.includes("____")))
        const rawAnswers = options?.code_expected_answers || exercise?.expected_answer || ""
        const answers = Array.isArray(rawAnswers) ? rawAnswers : [rawAnswers]
        const solution = completion
          ? answers.filter(Boolean).map((answer, index) => `Blank ${index + 1}: ${answer}`).join("\n")
          : exercise?.expected_answer
        if (solution) content += "\n\n## Suggested answer\n\n" +
          (exercise?.exercise_type === "code" || exercise?.exercise_type === "sql" ? "~~~\n" + solution + "\n~~~" : solution)
        if (exercise?.common_mistakes?.length) content += "\n\n## Common pitfalls\n\n" + exercise.common_mistakes.map((item) => "- " + item).join("\n")
      }
    }
  }

  if (explanation) citations = [...new Map(citations.map((citation) => [
    citation.document_id + ":" + citation.page_number, citation,
  ])).values()]
  if (citations.length) {
    const expected = citations.length
    const { data: documents, error } = await client.from("documents").select("id,filename,page_count")
      .eq("course_id", body.course_id).in("id", [...new Set(citations.map((citation) => citation.document_id))])
    if (error) return fail("Could not verify the PDF citations.", 503)
    citations = citations.flatMap((citation) => {
      const doc = documents.find((item) => item.id === citation.document_id)
      return doc && Number.isInteger(citation.page_number) && citation.page_number! > 0 &&
        (!doc.page_count || citation.page_number! <= doc.page_count) ? [{ ...citation, filename: doc.filename }] : []
    })
    if (sourcedMarkdown && citations.length !== expected) return fail("A source page is unavailable in this course.", 422)
  }

  if (explanation) {
    const authorized = new Map(citations.map((citation) => [
      citation.document_id + ":" + citation.page_number, citation,
    ]))
    const verify = (refs?: ExerciseCitation[] | null) => (refs ?? []).flatMap((citation) => {
      const match = authorized.get(citation.document_id + ":" + citation.page_number)
      return match ? [match] : []
    })
    content = explanationNoteText({
      ...explanation, citations: verify(explanation.citations),
      sections: explanation.sections?.map((section) => ({ ...section, citations: verify(section.citations) })),
    })
  }
  try { doc ??= validateNoteDocument(markdownNote(content)) }
  catch { return fail("This response could not be converted into a note.", 422) }
  const selection = body.selection?.replace(/\s+/g, " ").trim()
  const nodes = selection ? selectNoteText(doc, selection) : doc.content
  if (!nodes) return fail("Highlight text within one paragraph, heading, list item, or code block.", 422)
  let legacy: Json = null
  if (body.note_id) {
    const { data: note } = await client.from("notebook_notes").select("content,content_json,source_type")
      .eq("id", body.note_id).eq("user_id", user.id).maybeSingle()
    if (!note) return fail("Note not found.", 404)
    if (!note.content_json && note.content) {
      legacy = { original: note.content, nodes: readNoteDocument(null, note.content, note.source_type !== "manual").content as Json }
    }
  }
  const { data, error } = await service.rpc("capture_notebook_response", {
    owner: user.id, request: body.request_id, destination: body.note_id ?? null,
    source_course: body.course_id, source_session: session.id, source_message: body.message_id,
    source_kind: kind, source_citations: citations.map(({ document_id, filename, page_number }) => ({ document_id, filename, page_number })),
    fingerprint_arg: createHash("sha256").update(JSON.stringify([body.message_id.toLowerCase(), selection ?? ""])).digest("hex"),
    note_title: (typeof body.title === "string" ? body.title.trim().slice(0, 240) : "") || "Saved Socra response",
    body_nodes: nodes as Json, body_text: nodes.map(noteText).join("\n"), legacy_nodes: legacy,
  })
  if (error) return fail(error.code === "22001" ? "This note is too large to append to." : "Could not save the response.", error.code === "22001" ? 422 : 503)
  const result = data as { state: string; id: string } | null
  if (result?.state !== "saved") return fail("The note or original response is unavailable.", 404)
  return NextResponse.json({ id: result.id })
}
