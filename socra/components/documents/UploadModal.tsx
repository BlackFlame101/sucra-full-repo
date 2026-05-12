"use client"

import { useCallback, useRef, useState } from "react"
import { Upload, FileText, X, CheckCircle2, AlertCircle, Loader2 } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"

interface UploadModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  courseId: string
  onUploadComplete: () => void
}

type FileStatus = "pending" | "uploading" | "done" | "error"

interface QueuedFile {
  file: File
  status: FileStatus
  progress: number
  error?: string
  result?: { chunks: number; embeddings: number; pageCount: number | null }
}

const MAX_SIZE = 50 * 1024 * 1024

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function validateFile(file: File): string | null {
  if (file.type !== "application/pdf") return "Only PDF files are accepted."
  if (file.size > MAX_SIZE) return "File size exceeds 50MB limit."
  return null
}

export function UploadModal({
  open,
  onOpenChange,
  courseId,
  onUploadComplete,
}: UploadModalProps) {
  const [files, setFiles] = useState<QueuedFile[]>([])
  const [dragActive, setDragActive] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const addFiles = (newFiles: FileList | File[]) => {
    const toAdd: QueuedFile[] = []
    for (const file of Array.from(newFiles)) {
      const err = validateFile(file)
      if (err) {
        toAdd.push({ file, status: "error", progress: 0, error: err })
      } else {
        toAdd.push({ file, status: "pending", progress: 0 })
      }
    }
    setFiles((prev) => [...prev, ...toAdd])
  }

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(false)
    if (e.dataTransfer.files.length > 0) {
      addFiles(e.dataTransfer.files)
    }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(false)
  }, [])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(e.target.files)
      e.target.value = ""
    }
  }

  const uploadAll = async () => {
    const pendingFiles = files.filter((f) => f.status === "pending")
    if (pendingFiles.length === 0) return

    setIsUploading(true)
    let anySuccess = false

    for (let i = 0; i < files.length; i++) {
      if (files[i].status !== "pending") continue

      setFiles((prev) =>
        prev.map((f, idx) =>
          idx === i ? { ...f, status: "uploading" as const, progress: 30 } : f
        )
      )

      try {
        const formData = new FormData()
        formData.append("file", files[i].file)
        formData.append("courseId", courseId)
        try {
          const keys = JSON.parse(localStorage.getItem("socra_api_keys") || "{}")
          if (keys.google) formData.append("googleApiKey", keys.google)
        } catch { /* use server default */ }

        setFiles((prev) =>
          prev.map((f, idx) => (idx === i ? { ...f, progress: 50 } : f))
        )

        const res = await fetch("/api/upload", {
          method: "POST",
          body: formData,
        })

        const data = await res.json()

        if (!res.ok) {
          throw new Error(data.error || "Upload failed")
        }

        setFiles((prev) =>
          prev.map((f, idx) =>
            idx === i
              ? {
                  ...f,
                  status: "done" as const,
                  progress: 100,
                  result: {
                    chunks: data.chunks,
                    embeddings: data.embeddings,
                    pageCount: data.document?.page_count,
                  },
                }
              : f
          )
        )
        anySuccess = true
      } catch (err) {
        setFiles((prev) =>
          prev.map((f, idx) =>
            idx === i
              ? {
                  ...f,
                  status: "error" as const,
                  progress: 0,
                  error:
                    err instanceof Error ? err.message : "Upload failed",
                }
              : f
          )
        )
      }
    }

    setIsUploading(false)
    if (anySuccess) onUploadComplete()
  }

  const handleClose = (nextOpen: boolean) => {
    if (isUploading) return
    onOpenChange(nextOpen)
    if (!nextOpen) setFiles([])
  }

  const pendingCount = files.filter((f) => f.status === "pending").length
  const allDone =
    files.length > 0 && files.every((f) => f.status === "done" || f.status === "error")

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogDescription className="uppercase text-xs tracking-widest font-medium text-muted-foreground">
            Upload Documents
          </DialogDescription>
          <DialogTitle className="font-serif text-xl font-medium">
            Expand the Atelier
          </DialogTitle>
        </DialogHeader>

        <div className="py-4 space-y-4">
          {/* Drop Zone — always visible unless uploading */}
          {!isUploading && (
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
              className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 cursor-pointer transition-colors ${
                dragActive
                  ? "border-secondary bg-secondary/10"
                  : "border-border/50 bg-muted/30 hover:border-secondary/40 hover:bg-muted/50"
              }`}
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-card border border-border/50 mb-3">
                <Upload className="h-5 w-5 text-muted-foreground" />
              </div>
              <p className="font-serif text-sm italic text-muted-foreground mb-1">
                Drop your syllabus or PDFs here
              </p>
              <p className="text-xs text-muted-foreground/60 uppercase tracking-wider">
                Maximum file size 50MB &middot; Multiple files supported
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,application/pdf"
                multiple
                onChange={handleInputChange}
                className="hidden"
              />
            </div>
          )}

          {/* File List */}
          {files.length > 0 && (
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {files.map((qf, idx) => (
                <div
                  key={`${qf.file.name}-${idx}`}
                  className="flex items-center gap-3 rounded-lg bg-muted/40 border border-border/50 px-4 py-3"
                >
                  <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">
                      {qf.file.name}
                    </p>
                    {qf.status === "uploading" ? (
                      <div className="mt-1.5">
                        <Progress value={qf.progress} className="h-1.5" />
                      </div>
                    ) : qf.status === "done" ? (
                      <p className="text-xs text-secondary">
                        {qf.result?.pageCount} pages &middot; {qf.result?.chunks} chunks
                      </p>
                    ) : qf.status === "error" ? (
                      <p className="text-xs text-destructive">{qf.error}</p>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        {formatFileSize(qf.file.size)}
                      </p>
                    )}
                  </div>

                  {qf.status === "pending" && !isUploading && (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => removeFile(idx)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  )}
                  {qf.status === "uploading" && (
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" />
                  )}
                  {qf.status === "done" && (
                    <CheckCircle2 className="h-5 w-5 text-secondary shrink-0" />
                  )}
                  {qf.status === "error" && (
                    <AlertCircle className="h-5 w-5 text-destructive shrink-0" />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => handleClose(false)}
            disabled={isUploading}
          >
            {allDone ? "Close" : "Cancel"}
          </Button>
          {!allDone && (
            <Button
              onClick={uploadAll}
              disabled={pendingCount === 0 || isUploading}
            >
              {isUploading
                ? "Processing..."
                : `Upload ${pendingCount} ${pendingCount === 1 ? "file" : "files"}`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
