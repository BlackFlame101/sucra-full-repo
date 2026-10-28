import { NextResponse } from "next/server"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { chunkPages } from "@/lib/pdf/chunker"
import { parsePDF } from "@/lib/pdf/parser"
import { generateEmbeddings } from "@/lib/embeddings/generate"
import { createHash } from "node:crypto"

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
    const contentHash = createHash("sha256").update(buffer).digest("hex")
    const parsed = await parsePDF(buffer)
    const chunks = chunkPages(parsed.pages)

    if (chunks.length === 0) {
      return NextResponse.json({ error: "No text could be extracted" }, { status: 422 })
    }

    const serviceClient = await createServiceClient()
    const texts = chunks.map((c) => c.content)
    const embeddings = await generateEmbeddings(texts, googleApiKey)

    // Finish the expensive embedding step before replacing the current index.
    // A quota/provider failure then leaves the existing document searchable.
    await serviceClient.from("documents").update({
      content_hash: contentHash,
      page_count: parsed.pageCount,
      summary_status: "processing",
    }).eq("id", documentId)

    await serviceClient.from("embeddings").delete().eq("document_id", documentId)

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

    let summaryStatus: "ready" | "failed" = "failed"
    try {
      const response = await fetch(`${process.env.SOCRA_BACKEND_URL || "http://localhost:8000"}/documents/${documentId}/summarize`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages: parsed.pages, course_id: doc.course_id, content_hash: contentHash, google_api_key: googleApiKey }),
        signal: AbortSignal.timeout(120_000),
      })
      summaryStatus = response.ok ? "ready" : "failed"
    } catch (error) {
      console.warn("Summary regeneration deferred:", error)
    }
    await serviceClient.from("documents").update({ summary_status: summaryStatus }).eq("id", documentId)

    return NextResponse.json({ chunks: chunks.length, embeddings: stored, summaryStatus })
  } catch (error) {
    console.error("Re-embed error:", error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Re-embedding failed" },
      { status: 500 }
    )
  }
}
