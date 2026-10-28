import "@/lib/polyfills"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { parsePDF } from "@/lib/pdf/parser"
import { chunkPages } from "@/lib/pdf/chunker"
import { generateEmbeddings } from "@/lib/embeddings/generate"
import { isQuotaError } from "@/lib/ai/model-resolver"
import { NextResponse } from "next/server"
import { createHash } from "node:crypto"

const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB

export async function POST(request: Request) {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const formData = await request.formData()
  const file = formData.get("file") as File | null
  const courseId = formData.get("courseId") as string | null
  const googleApiKey = (formData.get("googleApiKey") as string | null) || undefined

  if (!file || !courseId) {
    return NextResponse.json(
      { error: "File and courseId are required" },
      { status: 400 }
    )
  }

  if (file.type !== "application/pdf") {
    return NextResponse.json(
      { error: "Only PDF files are accepted" },
      { status: 400 }
    )
  }

  if (file.size > MAX_FILE_SIZE) {
    return NextResponse.json(
      { error: "File size exceeds 50MB limit" },
      { status: 400 }
    )
  }

  // Verify the course belongs to this user
  const { data: course } = await supabase
    .from("courses")
    .select("id")
    .eq("id", courseId)
    .eq("user_id", user.id)
    .single()

  if (!course) {
    return NextResponse.json(
      { error: "Course not found" },
      { status: 404 }
    )
  }

  let storagePath: string | null = null
  let documentId: string | null = null
  let serviceClient: Awaited<ReturnType<typeof createServiceClient>> | null = null

  const rollbackUpload = async () => {
    if (documentId && serviceClient) {
      const embeddingsResult = await serviceClient.from("embeddings").delete().eq("document_id", documentId)
      const summariesResult = await serviceClient.from("document_summaries").delete().eq("document_id", documentId)
      const documentResult = await serviceClient.from("documents").delete().eq("id", documentId)
      if (embeddingsResult.error) console.error("Upload rollback: embeddings cleanup failed", embeddingsResult.error)
      if (summariesResult.error) console.error("Upload rollback: summaries cleanup failed", summariesResult.error)
      if (documentResult.error) console.error("Upload rollback: document cleanup failed", documentResult.error)
    } else if (documentId) {
      const { error } = await supabase.from("documents").delete().eq("id", documentId)
      if (error) console.error("Upload rollback: document cleanup failed", error)
    }

    if (storagePath) {
      const { error } = await supabase.storage.from("documents").remove([storagePath])
      if (error) console.error("Upload rollback: storage cleanup failed", error)
    }
    storagePath = null
    documentId = null
  }

  try {
    const arrayBuffer = await file.arrayBuffer()
    const buffer = Buffer.from(arrayBuffer)

    // 1. Upload to Supabase Storage
    // Sanitize filename for storage key: strip non-ASCII, collapse whitespace
    const safeName = file.name
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-zA-Z0-9._-]/g, "_")
      .replace(/_+/g, "_")
    storagePath = `${user.id}/${courseId}/${Date.now()}_${safeName}`
    const { error: uploadError } = await supabase.storage
      .from("documents")
      .upload(storagePath, buffer, {
        contentType: "application/pdf",
        upsert: false,
      })

    if (uploadError) {
      throw new Error(`Storage upload failed: ${uploadError.message}`)
    }

    // 2. Parse PDF
    const parsed = await parsePDF(buffer)
    const contentHash = createHash("sha256").update(buffer).digest("hex")

    // 3. Chunk text
    const chunks = chunkPages(parsed.pages)

    if (chunks.length === 0) {
      // Clean up uploaded file if no text could be extracted
      await rollbackUpload()
      return NextResponse.json(
        { error: "Could not extract text from PDF. The file may be image-based or empty." },
        { status: 422 }
      )
    }

    // 4. Create document record
    const { data: document, error: docError } = await supabase
      .from("documents")
      .insert({
        course_id: courseId,
        filename: file.name,
        storage_path: storagePath,
        page_count: parsed.pageCount,
        file_size: file.size,
        content_hash: contentHash,
        summary_status: "processing",
      })
      .select()
      .single()

    if (docError) {
      throw new Error(`Document record creation failed: ${docError.message}`)
    }
    documentId = document.id

    // 5. Generate embeddings and store them
    // Use service client for embedding inserts (bypasses RLS for batch operations)
    serviceClient = await createServiceClient()
    let embeddingsStored = 0

    try {
      const texts = chunks.map((c) => c.content)
      const embeddings = await generateEmbeddings(texts, googleApiKey)

      const embeddingRows = chunks.map((chunk, i) => ({
        document_id: document.id,
        content: chunk.content,
        embedding: JSON.stringify(embeddings[i]),
        page_number: chunk.pageNumber,
        chunk_index: chunk.chunkIndex,
        metadata: {
          filename: file.name,
          course_id: courseId,
        },
      }))

      // Insert in batches of 50
      for (let i = 0; i < embeddingRows.length; i += 50) {
        const batch = embeddingRows.slice(i, i + 50)
        const { error: embError } = await serviceClient
          .from("embeddings")
          .insert(batch)

        if (embError) {
          console.error("Embedding insert error:", embError)
          throw embError
        }
        embeddingsStored += batch.length
      }
    } catch (embeddingError) {
      console.error("Embedding generation failed:", embeddingError)
      const quota = isQuotaError(embeddingError)
      await rollbackUpload()
      if (quota) {
        return NextResponse.json({
          code: "QUOTA_EXCEEDED",
          error: "Embedding quota exceeded. The PDF was removed because processing did not complete. Wait for the quota window to reset or check your Gemini project limits, then try again.",
        }, { status: 429 })
      }
      throw embeddingError
    }

    // Summary generation runs after source chunks are stored. Its failure is
    // recorded for retry and never removes otherwise usable page citations.
    let summaryStatus: "ready" | "failed" | "not_applicable" = "failed"
    try {
      const summaryResponse = await fetch(`${process.env.SOCRA_BACKEND_URL || "http://localhost:8000"}/documents/${document.id}/summarize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages: parsed.pages, course_id: courseId, content_hash: contentHash, google_api_key: googleApiKey }),
        signal: AbortSignal.timeout(120_000),
      })
      summaryStatus = summaryResponse.ok ? "ready" : "failed"
    } catch (summaryError) {
      console.warn("Course summary generation deferred:", summaryError)
    }
    await serviceClient.from("documents").update({ summary_status: summaryStatus }).eq("id", document.id)

    return NextResponse.json({
      document,
      chunks: chunks.length,
      embeddings: embeddingsStored,
      summaryStatus,
    }, { status: 201 })
  } catch (error) {
    console.error("Upload pipeline error:", error)
    await rollbackUpload()
    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : "Upload processing failed",
      },
      { status: 500 }
    )
  }
}
