"use client"

import { FileText, Trash2, MoreVertical } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import type { Document } from "@/types"

interface DocumentItemProps {
  document: Document
  onDelete: (id: string) => void
}

function formatFileSize(bytes: number | null): string {
  if (!bytes) return ""
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function DocumentItem({ document, onDelete }: DocumentItemProps) {
  return (
    <div className="group flex items-center gap-3 rounded-lg border border-border/50 bg-card/40 px-4 py-3 transition-colors hover:bg-card/70">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-tertiary/10">
        <FileText className="h-4 w-4 text-tertiary" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">{document.filename}</p>
        <p className="text-xs text-muted-foreground">
          {document.page_count
            ? `${document.page_count} pages`
            : "Processing..."}
          {document.file_size ? ` · ${formatFileSize(document.file_size)}` : ""}
        </p>
      </div>
      <div className="opacity-0 group-hover:opacity-100 transition-opacity">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm">
              <MoreVertical className="h-4 w-4" />
              <span className="sr-only">Document options</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
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
