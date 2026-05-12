import "@/lib/polyfills"
import { createClient, createServiceClient } from "@/lib/supabase/server"
import { parsePDF } from "@/lib/pdf/parser"
import { chunkPages } from "@/lib/pdf/chunker"
import { generateEmbeddings } from "@/lib/embeddings/generate"
import { isQuotaError } from "@/lib/ai/model-resolver"
import { NextResponse } from "next/server"

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
    const storagePath = `${user.id}/${courseId}/${Date.now()}_${safeName}`
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

    // 3. Chunk text
    const chunks = chunkPages(parsed.pages)

    if (chunks.length === 0) {
      // Clean up uploaded file if no text could be extracted
      await supabase.storage.from("documents").remove([storagePath])
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
      })
      .select()
      .single()

    if (docError) {
      await supabase.storage.from("documents").remove([storagePath])
      throw new Error(`Document record creation failed: ${docError.message}`)
    }

    // 5. Generate embeddings and store them
    // Use service client for embedding inserts (bypasses RLS for batch operations)
    const serviceClient = await createServiceClient()
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
      return NextResponse.json({
        document,
        chunks: chunks.length,
        embeddings: 0,
        ...(quota
          ? { code: "QUOTA_EXCEEDED", warning: "API quota exceeded for embeddings. Configure your own Google API key in Settings." }
          : { warning: embeddingError instanceof Error
              ? embeddingError.message
              : "Embedding generation failed. RAG will not work for this document until embeddings are generated." }),
      }, { status: quota ? 429 : 201 })
    }

    return NextResponse.json({
      document,
      chunks: chunks.length,
      embeddings: embeddingsStored,
    }, { status: 201 })
  } catch (error) {
    console.error("Upload pipeline error:", error)
    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : "Upload processing failed",
      },
      { status: 500 }
    )
  }
}
