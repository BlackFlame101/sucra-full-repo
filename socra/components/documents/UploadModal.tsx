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
import { MAX_PDF_BYTES } from "@/lib/documents"
import { Progress } from "@/components/ui/progress"
import { discardPdfUpload, uploadInParallel, uploadPdf, UploadError, type TransferState } from "@/lib/pdf/direct-upload"

interface UploadModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  courseId: string
  onUploadComplete: () => void
}

type FileStatus = "pending" | "preparing" | "uploading" | "finalizing" | "paused" | "done" | "error"

interface QueuedFile {
  file: File
  status: FileStatus
  id: string
  retryable?: boolean
  bytes?: number
  error?: string
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function validateFile(file: File): string | null {
  if (file.type !== "application/pdf" && !(file.type === "" && /\.pdf$/i.test(file.name))) return "Only PDF files are accepted."
  if (file.size < 1) return "Choose a PDF that is not empty."
  if (file.size > MAX_PDF_BYTES) return "This PDF exceeds the file size limit."
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
  const controllers = useRef(new Map<string, AbortController>())
  const transfers = useRef(new Map<string, TransferState>())
  const batchActive = useRef(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const addFiles = (newFiles: FileList | File[]) => {
    const toAdd: QueuedFile[] = []
    for (const file of Array.from(newFiles)) {
      const err = validateFile(file)
      if (err) {
        toAdd.push({ file, status: "error", id: crypto.randomUUID(), error: err })
      } else {
        toAdd.push({ file, status: "pending", id: crypto.randomUUID() })
      }
    }
    setFiles((prev) => [...prev, ...toAdd])
  }

  const removeFile = (id: string) => {
    if (transfers.current.delete(id)) void discardPdfUpload(id)
    setFiles((previous) => previous.filter((item) => item.id !== id))
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
    const pending = files.filter((file) => file.status === "pending")
    if (!pending.length || batchActive.current) return
    batchActive.current = true
    setIsUploading(true)
    const update = (id: string, change: Partial<QueuedFile>) =>
      setFiles((previous) => previous.map((file) => file.id === id ? { ...file, ...change } : file))
    let completed = false
    try {
      await uploadInParallel(pending, async ({ id, file }) => {
        const controller = new AbortController()
        controllers.current.set(id, controller)
        const state = transfers.current.get(id) ?? {}
        transfers.current.set(id, state)
        try {
          await uploadPdf(file, courseId, id, state, controller.signal,
            (stage, bytes) => update(id, { status: stage, bytes }))
          update(id, { status: "done", bytes: file.size })
          transfers.current.delete(id)
          completed = true
        } catch (cause) {
          update(id, {
            status: controller.signal.aborted ? "paused" : "error",
            retryable: !(cause instanceof UploadError) || ![400, 401, 404, 410, 415, 422].includes(cause.status),
            error: controller.signal.aborted ? undefined : cause instanceof Error ? cause.message : "Upload failed.",
          })
        } finally {
          controllers.current.delete(id)
        }
      })
    } finally {
      batchActive.current = false
      setIsUploading(false)
      if (completed) onUploadComplete()
    }
  }

  const handleClose = (nextOpen: boolean) => {
    if (batchActive.current) return
    if (!nextOpen) {
      for (const id of transfers.current.keys()) void discardPdfUpload(id)
      transfers.current.clear()
      setFiles([])
    }
    onOpenChange(nextOpen)
  }

  const pendingCount = files.filter((f) => f.status === "pending").length
  const allDone =
    files.length > 0 && files.every((f) => f.status === "done" || f.status === "error" || f.status === "paused")

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
                Up to two transfers at a time. PDFs must contain searchable text.
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
              {files.map((qf) => (
                <div
                  key={qf.id}
                  className="flex items-center gap-3 rounded-lg bg-muted/40 border border-border/50 px-4 py-3"
                >
                  <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">
                      {qf.file.name}
                    </p>
                    {qf.status === "uploading" ? (
                      <div className="mt-1.5">
                        <Progress value={Math.min(100, Math.floor((qf.bytes ?? 0) / qf.file.size * 100))} aria-label="PDF transfer progress" />
                        <span className="text-xs text-muted-foreground">{formatFileSize(qf.bytes ?? 0)} of {formatFileSize(qf.file.size)}</span>
                      </div>
                    ) : qf.status === "preparing" || qf.status === "finalizing" || qf.status === "paused" ? (
                      <p role="status" className="text-xs text-muted-foreground">
                        {qf.status === "preparing" ? "Preparing PDF." : qf.status === "finalizing" ? "Checking stored PDF." : "Upload paused."}
                      </p>
                    ) : qf.status === "done" ? (
                      <p className="text-xs text-secondary">
                        Uploaded. Follow indexing on the course page.
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
                      onClick={() => removeFile(qf.id)}
                      aria-label="Remove file"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  )}
                  {(qf.status === "preparing" || qf.status === "uploading") && (
                    <Button type="button" size="sm" variant="ghost" onClick={() => controllers.current.get(qf.id)?.abort()}>Pause</Button>
                  )}
                  {qf.status === "finalizing" && <Loader2 className="h-4 w-4 animate-spin" />}
                  {(qf.status === "error" || qf.status === "paused") && qf.retryable && !isUploading && (
                    <Button type="button" size="sm" variant="ghost" onClick={() => setFiles((previous) =>
                      previous.map((file) => file.id === qf.id ? { ...file, status: "pending", error: undefined } : file)
                    )}>{qf.status === "paused" ? "Resume" : "Retry"}</Button>
                  )}
                  {(qf.status === "paused" || qf.status === "error") && !isUploading && (
                    <Button type="button" size="icon-sm" variant="ghost" aria-label="Discard upload" onClick={() => removeFile(qf.id)}>
                      <X className="h-4 w-4" />
                    </Button>
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
                ? "Uploading..."
                : `Upload ${pendingCount} ${pendingCount === 1 ? "file" : "files"}`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
