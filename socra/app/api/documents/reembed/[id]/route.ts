import { NextResponse } from "next/server"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { chunkPages } from "@/lib/pdf/chunker"
import { parsePDF } from "@/lib/pdf/parser"
import { generateEmbeddings } from "@/lib/embeddings/generate"

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: documentId } = await params
  const body = await request.json().catch(() => ({}))
  const googleApiKey: string | undefined = body.googleApiKey || undefined
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const { data: doc } = await supabase
    .from("documents")
    .select("*, courses!inner(user_id)")
    .eq("id", documentId)
    .single()

  if (!doc) {
    return NextResponse.json({ error: "Document not found" }, { status: 404 })
  }

  try {
    const { data: fileData, error: dlError } = await supabase.storage
      .from("documents")
      .download(doc.storage_path)

    if (dlError || !fileData) {
      throw new Error(`Failed to download file: ${dlError?.message}`)
    }

    const buffer = Buffer.from(await fileData.arrayBuffer())
    const parsed = await parsePDF(buffer)
    const chunks = chunkPages(parsed.pages)

    if (chunks.length === 0) {
      return NextResponse.json({ error: "No text could be extracted" }, { status: 422 })
    }

    const serviceClient = await createServiceClient()

    await serviceClient
      .from("embeddings")
      .delete()
      .eq("document_id", documentId)

    const texts = chunks.map((c) => c.content)
    const embeddings = await generateEmbeddings(texts, googleApiKey)

    const embeddingRows = chunks.map((chunk, i) => ({
      document_id: documentId,
      content: chunk.content,
      embedding: JSON.stringify(embeddings[i]),
      page_number: chunk.pageNumber,
      chunk_index: chunk.chunkIndex,
      metadata: {
        filename: doc.filename,
        course_id: doc.course_id,
      },
    }))

    let stored = 0
    for (let i = 0; i < embeddingRows.length; i += 50) {
      const batch = embeddingRows.slice(i, i + 50)
      const { error: embError } = await serviceClient
        .from("embeddings")
        .insert(batch)
      if (embError) throw embError
      stored += batch.length
    }

    return NextResponse.json({ chunks: chunks.length, embeddings: stored })
  } catch (error) {
    console.error("Re-embed error:", error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Re-embedding failed" },
      { status: 500 }
    )
  }
}
