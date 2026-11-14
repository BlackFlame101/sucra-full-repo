import { createClient, createServiceClient } from "@/lib/supabase/server"
import { ownedDocument } from "@/lib/server/document-jobs"
import { NextResponse } from "next/server"

export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  const document = await ownedDocument(supabase, id, user.id)
  if (!document) return NextResponse.json({ error: "Document not found" }, { status: 404 })

  const service = await createServiceClient()
  // Foreign keys remove jobs, vectors and summaries in the same transaction.
  const { error } = await service.from("documents").delete().eq("id", id).eq("course_id", document.course_id)
  if (error) return NextResponse.json({ error: "Could not delete this PDF." }, { status: 500 })

  return NextResponse.json({ success: true, storageCleanupPending: true })
}
