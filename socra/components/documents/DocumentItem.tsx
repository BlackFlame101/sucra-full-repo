"use client"

import { useState } from "react"
import { toast } from "sonner"
import { FileText, Trash2, MoreVertical } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import { requestPdfProcessing } from "@/lib/documents"
import { PdfCitation } from "@/components/documents/PdfCitation"
import type { Document } from "@/types"

interface DocumentItemProps {
  document: Document
  onDelete: (id: string) => void
  onProcessingChange: () => void
}

function formatFileSize(bytes: number | null): string {
  if (!bytes) return ""
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function DocumentItem({ document, onDelete, onProcessingChange }: DocumentItemProps) {
  const [retrying, setRetrying] = useState(false)
  const retry = async (kind: "index" | "summary" | "ocr") => {
    if (kind === "ocr" && !window.confirm("OCR runs locally and may take a few minutes. Indexing the recognized text uses Gemini embedding quota. Continue?")) return
    setRetrying(true)
    try {
      await requestPdfProcessing(document.id, kind)
      onProcessingChange()
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not queue this PDF.")
    } finally {
      setRetrying(false)
    }
  }
  const indexReady = (document.index_status ?? "ready") === "ready"
  const needsOcr = document.processing_error?.startsWith("Scanned PDF.") || document.processing_error?.startsWith("OCR")
  const summaryLabel = document.summary_stage ?? ({
    ready: "Course Map ready", failed: "Course Map failed", processing: "Generating Course Map",
    pending: indexReady ? "Course Map unavailable" : "Course Map pending",
  } as Record<string, string>)[document.summary_status]
  return (
    <div className="group flex items-center gap-3 rounded-lg border border-border/50 bg-card/40 px-4 py-3 transition-colors hover:bg-card/70">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-tertiary/10">
        <FileText className="h-4 w-4 text-tertiary" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate"><PdfCitation documentId={document.id} filename={document.filename} page={1} /></p>
        <p className="text-xs text-muted-foreground">
          {document.page_count
            ? `${document.page_count} pages`
            : "Processing..."}
          {document.file_size ? ` · ${formatFileSize(document.file_size)}` : ""}
        </p>
        <p role="status" className="text-xs text-muted-foreground">
          {indexReady ? "Searchable" : document.index_status === "failed" ? "Indexing failed" : "Indexing"}
          {document.index_stage && ` · ${document.index_stage}`}
          {summaryLabel && ` · ${summaryLabel}`}
        </p>
        {document.processing_error && <p className="text-xs text-destructive">{document.processing_error}</p>}
        {needsOcr && !document.index_stage && <p className="text-xs text-muted-foreground">OCR may take a few minutes. Text recognition runs locally, and indexing uses your Gemini embedding quota.</p>}
        {document.summary_error && <p className="text-xs text-destructive">{document.summary_error}</p>}
      </div>
      <div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm">
              <MoreVertical className="h-4 w-4" />
              <span className="sr-only">Document options</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {!document.index_stage && (indexReady || document.index_status === "failed") && (
              <DropdownMenuItem disabled={retrying} onClick={() => void retry("ocr")}>Run OCR on scanned pages</DropdownMenuItem>
            )}
            {(indexReady || document.index_status === "failed") && !document.index_stage && !needsOcr && (
              <DropdownMenuItem disabled={retrying} onClick={() => void retry("index")}>
                {document.processing_error ? "Retry indexing" : "Rebuild index"}
              </DropdownMenuItem>
            )}
            {indexReady && !document.summary_stage && !document.index_stage && document.summary_status !== "ready" && (
              <DropdownMenuItem disabled={retrying} onClick={() => void retry("summary")}>Retry Course Map</DropdownMenuItem>
            )}
            <DropdownMenuItem
              variant="destructive"
              onClick={() => onDelete(document.id)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete document
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
