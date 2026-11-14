"use client"

import { useCallback, useRef, useState } from "react"
import { uploadPdf, type TransferState } from "@/lib/pdf/direct-upload"

export type UploadStatus = "idle" | "uploading" | "done" | "error"

export interface UploadResult {
  document: {
    id: string
    filename: string
    page_count: number | null
    file_size: number | null
  }
  indexStatus: string
  summaryStatus: string
}

export function useUpload(courseId: string) {
  const transfers = useRef(new WeakMap<File, { id: string; state: TransferState }>())
  const [status, setStatus] = useState<UploadStatus>("idle")
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<UploadResult | null>(null)

  const upload = useCallback(
    async (file: File): Promise<UploadResult | null> => {
      setStatus("uploading")
      setProgress(0)
      setError(null)
      setResult(null)

      try {
        const transfer = transfers.current.get(file) ?? { id: crypto.randomUUID(), state: {} }
        transfers.current.set(file, transfer)
        const data = await uploadPdf<UploadResult>(file, courseId, transfer.id, transfer.state,
          new AbortController().signal, (_, bytes) => setProgress(Math.floor(bytes / file.size * 100)))
        transfers.current.delete(file)

        setProgress(100)
        setStatus("done")
        setResult(data)
        return data
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Something went wrong"
        setError(message)
        setStatus("error")
        return null
      }
    },
    [courseId]
  )

  const reset = useCallback(() => {
    setStatus("idle")
    setProgress(0)
    setError(null)
    setResult(null)
  }, [])

  return { upload, status, progress, error, result, reset }
}
