import { createClient, createServiceClient } from "@/lib/supabase/server"
import { readSavedExplanation } from "@/lib/server/saved-explanation"
import { educationalCitations, isEducationalDocument } from "@/lib/educational-document"
import { NextResponse } from "next/server"

export async function GET() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { data: courses, error: courseError } = await supabase
    .from("courses").select("id,name,description,updated_at").eq("user_id", user.id)
    .order("updated_at", { ascending: false })
  if (courseError) return NextResponse.json({ error: courseError.message }, { status: 500 })

  const courseIds = (courses ?? []).map((course) => course.id)
  const [documentsResult, itemsResult] = await Promise.all([
    courseIds.length
      ? supabase.from("documents").select("id,course_id,filename,file_size,page_count,created_at,summary_status")
          .in("course_id", courseIds).order("created_at", { ascending: false })
      : Promise.resolve({ data: [], error: null }),
    supabase.from("library_items").select("*").eq("user_id", user.id)
      .order("created_at", { ascending: false }),
  ])
  if (documentsResult.error) return NextResponse.json({ error: documentsResult.error.message }, { status: 500 })
  if (itemsResult.error) return NextResponse.json({ error: itemsResult.error.message }, { status: 500 })

  const courseNames = new Map((courses ?? []).map((course) => [course.id, course.name]))
  return NextResponse.json({
    courses: courses ?? [],
    documents: (documentsResult.data ?? []).map((document) => ({
      ...document,
      course_name: courseNames.get(document.course_id) ?? "Course",
    })),
    saved_items: (itemsResult.data ?? []).map((item) => ({
      ...item,
      course_name: courseNames.get(item.course_id) ?? "Course",
    })),
  })
}

export async function POST(request: Request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await request.json().catch(() => null)
  if (!body || !["explanation", "exercise"].includes(body.item_type) ||
      typeof body.course_id !== "string" || typeof body.title !== "string" || body.title.length > 240 ||
      !body.title.trim() || !body.content || typeof body.content !== "object" || JSON.stringify(body.content).length > 250_000) {
    return NextResponse.json({ error: "A course, title, item type, and saved content are required." }, { status: 400 })
  }
  const { data: course } = await supabase.from("courses").select("id")
    .eq("id", body.course_id).eq("user_id", user.id).single()
  if (!course) return NextResponse.json({ error: "Course not found." }, { status: 404 })
  if (body.item_type === "explanation") {
    const explanation = await readSavedExplanation(supabase, user.id, course.id, body.content)
    if (!explanation) return NextResponse.json({ error: "A completed explanation from this inquiry is required." }, { status: 404 })
    body.content = { session_id: body.content.session_id, message_id: body.content.message_id, explanation }
    const refs = isEducationalDocument(explanation) ? educationalCitations(explanation) : explanation.citations
    body.source_document_id = refs[0]?.document_id
    body.source_page = refs[0]?.page_number
  }
  let sourceDocumentId = typeof body.source_document_id === "string" ? body.source_document_id : null
  if (sourceDocumentId) {
    const { data: sourceDocument } = await supabase.from("documents").select("id")
      .eq("id", sourceDocumentId).eq("course_id", course.id).single()
    if (!sourceDocument && body.item_type === "explanation") sourceDocumentId = null
    else if (!sourceDocument) return NextResponse.json({ error: "Source document not found." }, { status: 404 })
  }

  const { data: item, error } = await (await createServiceClient()).from("library_items").insert({
    user_id: user.id,
    course_id: course.id,
    item_type: body.item_type,
    title: body.title.trim().slice(0, 240),
    content: body.content,
    source_document_id: sourceDocumentId,
    source_page: sourceDocumentId && Number.isInteger(body.source_page) && body.source_page > 0 ? body.source_page : null,
  }).select().single()
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(item, { status: 201 })
}
