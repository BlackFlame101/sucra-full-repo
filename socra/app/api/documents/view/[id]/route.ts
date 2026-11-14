import { ownedDocument } from "@/lib/server/document-jobs"
import { createClient, createServiceClient } from "@/lib/supabase/server"

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  if (!user) return new Response("Sign in to open this PDF.", { status: 401 })
  const document = await ownedDocument(client, id, user.id)
  if (!document || !document.storage_path.startsWith(`${user.id}/${document.course_id}/`)) {
    return new Response("PDF not found.", { status: 404 })
  }
  const page = Number(new URL(request.url).searchParams.get("page") ?? 1)
  if (!Number.isSafeInteger(page) || page < 1 || (document.page_count && page > document.page_count)) {
    return new Response("This page is not available in the PDF.", { status: 404 })
  }
  const service = await createServiceClient()
  const { data } = await service.storage.from("documents").createSignedUrl(document.storage_path, 120)
  if (!data) return new Response("Could not open the PDF. Try again.", { status: 503 })
  const url = new URL(data.signedUrl)
  url.hash = `page=${page}`
  return new Response(null, { status: 302, headers: { Location: url.href, "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" } })
}
