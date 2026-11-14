export const MAX_PDF_BYTES = 50 * 1024 * 1024
export const TUS_CHUNK_BYTES = 6 * 1024 * 1024

export function isPdfProcessing(document: { index_stage?: string | null; summary_stage?: string | null }) {
  return Boolean(document.index_stage || document.summary_stage)
}

export async function requestPdfProcessing(documentId: string, kind: "index" | "summary" | "ocr") {
  let googleApiKey: string | undefined
  try { googleApiKey = JSON.parse(localStorage.getItem("socra_api_keys") || "{}").google } catch { /* Use server key. */ }
  const response = await fetch(`/api/documents/reembed/${encodeURIComponent(documentId)}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, googleApiKey }),
  })
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.error ?? "Could not queue this PDF.")
}
