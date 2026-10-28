import { NextResponse } from "next/server"
import { createClient as createSupabaseClient } from "@supabase/supabase-js"
import { createClient } from "@/lib/supabase/server"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ courseId: string }> }
) {
  const { courseId } = await params
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const { data: course } = await supabase
    .from("courses")
    .select("id")
    .eq("id", courseId)
    .eq("user_id", user.id)
    .single()

  if (!course) {
    return NextResponse.json({ error: "Course not found" }, { status: 404 })
  }

  const { data: documents, error: documentsError } = await supabase
    .from("documents")
    .select("id, filename, content_hash, summary_status")
    .eq("course_id", courseId)
    .order("created_at", { ascending: false })

  if (documentsError) {
    return NextResponse.json({ error: documentsError.message }, { status: 500 })
  }

  if (!documents?.length) return NextResponse.json([])

  // The summary table is private to the backend. RLS intentionally denies
  // browser clients, so use a server-only client after checking course owner.
  let summaries: Array<{
    document_id: string
    document_version: string
    level: "document" | "section"
    section_index: number | null
    title: string
    summary: string
    page_start: number
    page_end: number
  }> | null = null
  let summariesError: unknown = null
  try {
    const serviceClient = createSupabaseClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!,
      { auth: { autoRefreshToken: false, persistSession: false } }
    )
    const result = await serviceClient
      .from("document_summaries")
      .select("document_id, document_version, level, section_index, title, summary, page_start, page_end")
      .eq("course_id", courseId)
      .order("page_start", { ascending: true })
    summaries = result.data
    summariesError = result.error
  } catch (error) {
    summariesError = error
  }

  // Keep document names available even when the summary migration has not
  // been applied or a document has not been summarized yet.
  const currentSummaries = summariesError
    ? []
    : (summaries ?? []).filter((summary) =>
        documents.some((document) =>
          document.id === summary.document_id &&
          document.content_hash === summary.document_version
        )
      )

  return NextResponse.json(
    documents.map((document) => ({
      documentId: document.id,
      filename: document.filename,
      status: document.summary_status,
      summary: currentSummaries.find(
        (summary) => summary.document_id === document.id && summary.level === "document"
      ) ?? null,
      sections: currentSummaries
        .filter((summary) => summary.document_id === document.id && summary.level === "section")
        .map((summary) => ({
          title: summary.title,
          summary: summary.summary,
          pageStart: summary.page_start,
          pageEnd: summary.page_end,
        })),
    }))
  )
}
