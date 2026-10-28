import { createClient, createServiceClient } from "@/lib/supabase/server"
import { NextResponse } from "next/server"

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  // Fetch the document and verify ownership via course
  const { data: document } = await supabase
    .from("documents")
    .select("*, courses!inner(user_id)")
    .eq("id", id)
    .single()

  if (
    !document ||
    (document.courses as unknown as { user_id: string }).user_id !== user.id
  ) {
    return NextResponse.json({ error: "Document not found" }, { status: 404 })
  }

  // Delete embeddings first (service client to bypass RLS)
  const serviceClient = await createServiceClient()
  await serviceClient.from("embeddings").delete().eq("document_id", id)
  await serviceClient.from("document_summaries").delete().eq("document_id", id)

  // Delete file from storage
  await supabase.storage
    .from("documents")
    .remove([document.storage_path])

  // Delete document record
  const { error } = await supabase.from("documents").delete().eq("id", id)

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  return NextResponse.json({ success: true })
}
