import { createClient } from "@/lib/supabase/server"
import { NextResponse } from "next/server"

const sourceTypes = ["manual", "explanation", "exercise"] as const

export async function GET() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const [notesResult, coursesResult] = await Promise.all([
    supabase.from("notebook_notes").select("*").eq("user_id", user.id)
      .order("updated_at", { ascending: false }),
    supabase.from("courses").select("id,name").eq("user_id", user.id)
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
  if (!body || typeof body.title !== "string" || !body.title.trim() || typeof body.content !== "string") {
    return NextResponse.json({ error: "A title and note content are required." }, { status: 400 })
  }
  const sourceType = sourceTypes.includes(body.source_type) ? body.source_type : "manual"
  let courseId: string | null = typeof body.course_id === "string" && body.course_id ? body.course_id : null
  if (courseId) {
    const { data: course } = await supabase.from("courses").select("id")
      .eq("id", courseId).eq("user_id", user.id).single()
    if (!course) return NextResponse.json({ error: "Course not found." }, { status: 404 })
  }
  const sourceDocumentId = typeof body.source_document_id === "string" ? body.source_document_id : null
  if (sourceDocumentId) {
    const { data: document } = await supabase.from("documents").select("id,course_id")
      .eq("id", sourceDocumentId).single()
    if (!document) return NextResponse.json({ error: "Source document not found." }, { status: 404 })
    if (courseId && document.course_id !== courseId) return NextResponse.json({ error: "Source document does not belong to this course." }, { status: 400 })
    const { data: documentCourse } = await supabase.from("courses").select("id")
      .eq("id", document.course_id).eq("user_id", user.id).single()
    if (!documentCourse) return NextResponse.json({ error: "Source document not found." }, { status: 404 })
    courseId = document.course_id
  }
  const { data: note, error } = await supabase.from("notebook_notes").insert({
    user_id: user.id,
    course_id: courseId,
    title: body.title.trim().slice(0, 240),
    topic: typeof body.topic === "string" ? body.topic.trim().slice(0, 120) : "",
    content: body.content,
    source_type: sourceType,
    source_data: body.source_data && typeof body.source_data === "object" ? body.source_data : {},
    source_document_id: sourceDocumentId,
    source_page: Number.isInteger(body.source_page) && body.source_page > 0 ? body.source_page : null,
  }).select().single()
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(note, { status: 201 })
}
