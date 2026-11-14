import { NextResponse } from "next/server"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { protectDocumentKey, uuidPattern } from "@/lib/server/document-jobs"
import { MAX_PDF_BYTES, TUS_CHUNK_BYTES } from "@/lib/documents"

const failure = (error: string, status: number) => NextResponse.json({ error }, { status })

function uploadRpcFailure(operation: string, uploadId: string, code: string | undefined, message: string) {
  console.error(`pdf_upload_rpc_failed operation=${operation} request_id=${uploadId} code=${code || "unknown"}`)
  if (code === "PGRST202") {
    return failure("PDF uploads are unavailable because the connected database is missing the upload functions. Ask the administrator to check the database migrations.", 503)
  }
  return failure(message, 503)
}

export async function POST(request: Request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return failure("Sign in to upload a PDF.", 401)
  if (!request.headers.get("content-type")?.startsWith("application/json")) {
    return failure("Use the direct PDF upload flow.", 415)
  }
  const body = await request.json().catch(() => null)
  if (typeof body?.uploadId !== "string" || !uuidPattern.test(body.uploadId)) {
    return failure("Invalid upload ID.", 400)
  }
  const uploadId = body.uploadId.toLowerCase()
  const service = await createServiceClient()
  const bucket = service.storage.from("documents")

  if (body.action === "cancel") {
    const { error } = await service.rpc("cancel_pdf_upload", { owner: user.id, upload_id: uploadId })
    if (error) return uploadRpcFailure("cancel_pdf_upload", uploadId, error.code, "Could not cancel the upload.")
    return NextResponse.json({ ok: true })
  }

  if (body.action === "finish") {
    let credential: string | undefined
    try {
      credential = protectDocumentKey(body.googleApiKey, uploadId)
    } catch (cause) {
      return failure((cause as Error).message, 400)
    }
    const started = performance.now()
    const { data, error } = await service.rpc("finish_pdf_upload", {
      owner: user.id, upload_id: uploadId, ...(credential ? { credential } : {}),
    })
    console.info("pdf_upload_timing", { request_id: uploadId, stage: "finalize",
      duration_ms: Math.round(performance.now() - started), status: data?.state ?? "error" })
    if (error || !data) {
      return uploadRpcFailure("finish_pdf_upload", uploadId, error?.code, "Could not confirm indexing. Retry to finish the upload.")
    }
    if (data.state === "processing_quota") return failure("Your PDF processing queue is full. Retry after some jobs finish.", 429)
    if (data.state === "incomplete") return failure("Storage has not confirmed a complete PDF of the declared size.", 409)
    if (data.state === "expired") return failure("This upload expired. Select the file again.", 410)
    if (!data.document) return failure("Upload not found.", 404)
    return NextResponse.json({ document: data.document, indexStatus: data.document.index_status,
      summaryStatus: data.document.summary_status }, { status: 202 })
  }

  if (body.action !== "reserve" || typeof body.courseId !== "string" || !uuidPattern.test(body.courseId) ||
      typeof body.filename !== "string" || !body.filename.trim() || body.filename.length > 255 ||
      !Number.isSafeInteger(body.size) || body.size < 1 || body.size > MAX_PDF_BYTES ||
      typeof body.digest !== "string" || !/^[a-f0-9]{64}$/.test(body.digest)) {
    return failure("Select a valid PDF for this course.", 400)
  }
  const { data, error } = await service.rpc("reserve_pdf_upload", {
    owner: user.id, course: body.courseId, upload_id: uploadId,
    filename_arg: body.filename, size_arg: body.size, digest_arg: body.digest,
  })
  if (error || !data) {
    return uploadRpcFailure("reserve_pdf_upload", uploadId, error?.code, "Could not prepare the upload. Retry shortly.")
  }
  if (data.state === "upload_quota") return failure("Your upload limit is reached. Finish pending uploads or try again tomorrow.", 429)
  if (data.state === "expired" || data.state === "cancelled") return failure("This upload expired or was cancelled. Select the file again.", 410)
  if (!data.path) return failure("Course or upload not found.", 404)
  if (data.state === "finished") return NextResponse.json({ stored: true })

  const { data: info } = await bucket.info(data.path)
  if (info) return NextResponse.json({ stored: true })
  const { data: signed, error: signError } = await bucket.createSignedUploadUrl(data.path, { upsert: false })
  if (signError || !signed) return failure("Could not authorize transfer to Storage. Retry shortly.", 503)
  const storage = new URL(process.env.NEXT_PUBLIC_SUPABASE_URL!)
  if (/^[a-z0-9]+\.supabase\.co$/.test(storage.hostname)) {
    storage.hostname = storage.hostname.replace(".supabase.co", ".storage.supabase.co")
  }
  return NextResponse.json({
    path: data.path, signedUrl: signed.signedUrl, token: signed.token,
    resumableUrl: body.size > TUS_CHUNK_BYTES ? new URL("/storage/v1/upload/resumable/sign", storage).href : undefined,
  })
}
