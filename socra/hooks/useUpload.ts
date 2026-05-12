"use client"

import { useCallback, useState } from "react"

export type UploadStatus = "idle" | "uploading" | "processing" | "done" | "error"

export interface UploadResult {
  document: {
    id: string
    filename: string
    page_count: number | null
    file_size: number | null
  }
  chunks: number
  embeddings: number
  warning?: string
}

export function useUpload(courseId: string) {
  const [status, setStatus] = useState<UploadStatus>("idle")
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<UploadResult | null>(null)

  const upload = useCallback(
    async (file: File): Promise<UploadResult | null> => {
      setStatus("uploading")
      setProgress(10)
      setError(null)
      setResult(null)

      try {
        const formData = new FormData()
        formData.append("file", file)
        formData.append("courseId", courseId)

        setProgress(30)
        setStatus("processing")

        const res = await fetch("/api/upload", {
          method: "POST",
          body: formData,
        })

        setProgress(80)

        const data = await res.json()

        if (!res.ok) {
          throw new Error(data.error || "Upload failed")
        }

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
