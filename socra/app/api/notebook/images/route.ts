import { randomUUID } from "node:crypto"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { notebookImageBucket, ownsNotebookImagePath } from "@/lib/notebook/images"
import { prepareNotebookImage } from "@/lib/server/notebook-image"

export const runtime = "nodejs"
const privateHeaders = { "Cache-Control": "private, no-store" }

export async function POST(request: Request) {
  if (process.env.NOTEBOOK_IMAGE_UPLOADS !== "1") {
    return Response.json({ error: "Notebook image uploads are unavailable." }, { status: 503 })
  }
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  if (!user) return Response.json({ error: "Sign in to upload an image." }, { status: 401 })
  let image
  try { image = await prepareNotebookImage(request) }
  catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Invalid image." }, { status: 400 })
  }
  const path = `${user.id}/${randomUUID()}.${image.extension}`
  const service = await createServiceClient()
  const { error } = await service.storage.from(notebookImageBucket)
    .upload(path, image.data, { contentType: image.type, upsert: false })
  if (error) return Response.json({ error: "Could not store the image." }, { status: 503 })
  return Response.json({ path }, { status: 201, headers: privateHeaders })
}

export async function GET(request: Request) {
  const client = await createClient()
  const { data: { user } } = await client.auth.getUser()
  const path = new URL(request.url).searchParams.get("path")
  if (!user || !ownsNotebookImagePath(path, user.id)) {
    return new Response("Image not found.", { status: 404, headers: privateHeaders })
  }
  const { data, error } = await client.storage.from(notebookImageBucket).createSignedUrl(path, 120)
  return data && !error
    ? new Response(null, { status: 307, headers: { ...privateHeaders, Location: data.signedUrl } })
    : new Response("Image not found.", { status: 404, headers: privateHeaders })
}
