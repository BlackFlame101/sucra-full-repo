import { NextResponse } from "next/server"
import { ownedDocument, protectDocumentKey } from "@/lib/server/document-jobs"
import { createClient, createServiceClient } from "@/lib/supabase/server"

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  const document = await ownedDocument(supabase, id, user.id)
  if (!document) return NextResponse.json({ error: "Document not found" }, { status: 404 })

  const body = await request.json().catch(() => null)
  const kind = body?.kind ?? "index"
  if ((kind === "index" || kind === "ocr") && document.index_stage) {
    return NextResponse.json({ document, indexStatus: document.index_status, summaryStatus: document.summary_status }, { status: 202 })
  }
  if (kind !== "index" && kind !== "summary" && kind !== "ocr") {
    return NextResponse.json({ error: "Choose indexing or Course Map processing." }, { status: 400 })
  }
  if (kind === "summary" && document.index_status !== "ready") {
    return NextResponse.json({ error: "Wait until the PDF is searchable before retrying the Course Map." }, { status: 409 })
  }
  let credential: string | undefined
  try {
    credential = protectDocumentKey(body?.googleApiKey, id)
  } catch (cause) {
    return NextResponse.json({ error: (cause as Error).message }, { status: 400 })
  }

  const service = await createServiceClient()
  const { data: allowed, error: quotaError } = await service.rpc("consume_study_quota", {
    owner: user.id, operation_name: kind === "ocr" ? "pdf_ocr" : "pdf_retry",
  })
  if (quotaError) return NextResponse.json({ error: "PDF processing is temporarily unavailable." }, { status: 503 })
  if (!allowed) return NextResponse.json({ error: "PDF retry limit reached. Try again later." }, { status: 429 })
  const { data, error } = await service.rpc("retry_pdf_with_quota", {
    owner: user.id, document: id, job_kind: kind, ...(credential ? { credential } : {}),
  })
  if (data?.state === "processing_quota") {
    return NextResponse.json({ error: "Your PDF processing queue is full. Retry after some jobs finish." }, { status: 429 })
  }
  if (error || !data?.document) {
    return NextResponse.json({ error: "Could not queue this PDF. Try again shortly." }, { status: 409 })
  }
  return NextResponse.json({ document: data.document, indexStatus: data.document.index_status, summaryStatus: data.document.summary_status }, { status: 202 })
}
