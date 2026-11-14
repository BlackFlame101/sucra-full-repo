import { NextResponse } from "next/server"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { isPdfProcessing } from "@/lib/documents"

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

  const { data: course, error } = await supabase
    .from("courses")
    .select("documents(id, filename, content_hash, summary_status, index_status, index_stage, summary_stage, processing_error)")
    .eq("id", courseId)
    .eq("user_id", user.id)
    .order("created_at", { referencedTable: "documents", ascending: false })
    .maybeSingle()

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }
  if (!course) {
    return NextResponse.json({ error: "Course not found" }, { status: 404 })
  }

  const { documents } = course
  if (!documents.length) return NextResponse.json([])

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
    const serviceClient = await createServiceClient()
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
          document.index_status === "ready" &&
          document.id === summary.document_id &&
          document.content_hash === summary.document_version
        )
      )

  return NextResponse.json(
    documents.map((document) => ({
      documentId: document.id,
      filename: document.filename,
      status: document.summary_status,
      indexStatus: document.index_status,
      ocrRequired: /^(Scanned PDF[.]|OCR)/.test(document.processing_error ?? ""),
      processing: isPdfProcessing(document),
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
