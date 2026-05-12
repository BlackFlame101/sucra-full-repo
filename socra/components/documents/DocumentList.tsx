"use client"

import { DocumentItem } from "@/components/documents/DocumentItem"
import { Skeleton } from "@/components/ui/skeleton"
import { FileText } from "lucide-react"
import type { Document } from "@/types"

interface DocumentListProps {
  documents: Document[]
  loading: boolean
  onDelete: (id: string) => void
}

function DocumentSkeleton() {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border/50 bg-card/40 px-4 py-3">
      <Skeleton className="h-9 w-9 rounded-md" />
      <div className="flex-1 space-y-1.5">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-1/3" />
      </div>
    </div>
  )
}

export function DocumentList({
  documents,
  loading,
  onDelete,
}: DocumentListProps) {
  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <DocumentSkeleton key={i} />
        ))}
      </div>
    )
  }

  if (documents.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border/50 bg-card/20 p-8 text-center">
        <FileText className="h-8 w-8 text-muted-foreground/40 mx-auto mb-3" />
        <p className="text-sm text-muted-foreground">
          No documents uploaded yet. Upload a PDF to get started.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {documents.map((doc) => (
        <DocumentItem key={doc.id} document={doc} onDelete={onDelete} />
      ))}
    </div>
  )
}
