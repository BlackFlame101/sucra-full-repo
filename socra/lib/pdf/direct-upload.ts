import { TUS_CHUNK_BYTES } from "@/lib/documents"

export interface TransferState {
  resumableLocation?: string
  transferred?: boolean
  digest?: string
}

interface Destination {
  stored?: boolean
  path?: string
  signedUrl?: string
  token?: string
  resumableUrl?: string
}

export class UploadError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

async function uploadAction<T>(payload: object, signal?: AbortSignal): Promise<T> {
  const response = await fetch("/api/upload", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload), signal,
  })
  const result = await response.json().catch(() => null)
  if (!response.ok || !result) throw new UploadError(result?.error ?? "The upload request failed.", response.status)
  return result
}

function transfer(method: string, url: string, headers: Record<string, string>, body: Blob | null,
  signal: AbortSignal, progress?: (bytes: number) => void): Promise<XMLHttpRequest> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return }
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()
    xhr.open(method, url)
    xhr.timeout = body && body.size > 0 ? 180_000 : 30_000
    for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value)
    if (progress) xhr.upload.addEventListener("progress", (event) => progress(event.loaded))
    xhr.onload = () => resolve(xhr)
    xhr.onerror = () => reject(new Error("The connection to Storage was interrupted. Retry to continue."))
    xhr.ontimeout = () => reject(new Error("Storage took too long to respond. Retry to continue."))
    xhr.onabort = () => reject(signal.reason ?? new DOMException("Upload paused.", "AbortError"))
    xhr.onloadend = () => signal.removeEventListener("abort", abort)
    signal.addEventListener("abort", abort, { once: true })
    xhr.send(body)
  })
}

const publicKey = () => ({ apikey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "" })
const ok = (response: XMLHttpRequest) => response.status >= 200 && response.status < 300

function resumableLocation(location: string, endpoint: string) {
  const url = new URL(location, endpoint)
  const base = new URL(endpoint)
  if (url.origin !== base.origin || !url.pathname.startsWith("/storage/v1/upload/resumable/")) {
    throw new Error("Storage returned an unexpected upload destination.")
  }
  return url.href
}

async function resumableUpload(file: File, destination: Required<Pick<Destination, "path" | "token" | "resumableUrl">>,
  state: TransferState, signal: AbortSignal, progress: (bytes: number) => void) {
  const endpoint = destination.resumableUrl
  const headers = { ...publicKey(), "Tus-Resumable": "1.0.0", "x-signature": destination.token }
  let offset = 0
  if (state.resumableLocation) {
    const existing = await transfer("HEAD", resumableLocation(state.resumableLocation, endpoint), headers, null, signal)
    if (ok(existing)) {
      const rawOffset = existing.getResponseHeader("Upload-Offset")
      offset = rawOffset === null ? -1 : Number(rawOffset)
      if (!Number.isSafeInteger(offset) || offset < 0 || offset > file.size) throw new Error("Invalid upload offset from Storage.")
    } else if (existing.status === 404 || existing.status === 410) {
      delete state.resumableLocation
    } else {
      throw new Error("Could not check the existing upload. Retry to resume.")
    }
  }
  if (!state.resumableLocation) {
    const metadata = Object.entries({ bucketName: "documents", objectName: destination.path, contentType: "application/pdf" })
      .map(([name, value]) => name + " " + btoa(value)).join(",")
    const created = await transfer("POST", endpoint, { ...headers, "Upload-Length": String(file.size),
      "Upload-Metadata": metadata }, null, signal)
    const location = created.getResponseHeader("Location")
    if (!ok(created) || !location) throw new Error("Storage could not start the resumable transfer. Retry shortly.")
    state.resumableLocation = resumableLocation(location, endpoint)
  }
  progress(offset)
  while (offset < file.size) {
    const end = Math.min(offset + TUS_CHUNK_BYTES, file.size)
    const patched = await transfer("PATCH", state.resumableLocation, { ...headers,
      "Content-Type": "application/offset+octet-stream", "Upload-Offset": String(offset) },
    file.slice(offset, end), signal, (bytes) => progress(Math.min(offset + bytes, file.size)))
    if (!ok(patched) || patched.getResponseHeader("Upload-Offset") !== String(end)) {
      throw new Error("Storage did not confirm the uploaded chunk. Retry to resume.")
    }
    offset = end
  }
}

export async function uploadPdf<T>(file: File, courseId: string, uploadId: string, state: TransferState,
  signal: AbortSignal, onProgress: (stage: "preparing" | "uploading" | "finalizing", bytes: number) => void) {
  onProgress("preparing", 0)
  if (!state.digest) {
    if (!(await file.slice(0, 1024).text()).includes("%PDF-")) throw new UploadError("This file has no PDF header.", 422)
    const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer())
    state.digest = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")
  }
  let googleApiKey: string | undefined
  try { googleApiKey = JSON.parse(localStorage.getItem("socra_api_keys") || "{}").google } catch { /* default key */ }
  if (!state.transferred) {
    const target = await uploadAction<Destination>({
      action: "reserve", uploadId, courseId, filename: file.name, size: file.size, digest: state.digest,
    }, signal)
    if (!target.stored) {
      onProgress("uploading", 0)
      const progress = (bytes: number) => onProgress("uploading", bytes)
      if (target.resumableUrl && target.path && target.token) {
        await resumableUpload(file, { resumableUrl: target.resumableUrl, path: target.path, token: target.token },
          state, signal, progress)
      } else if (target.signedUrl) {
        const response = await transfer("PUT", target.signedUrl,
          { ...publicKey(), "Content-Type": "application/pdf", "x-upsert": "false" }, file, signal, progress)
        if (!ok(response)) throw new Error("Storage rejected the transfer. Retry the upload.")
      } else {
        throw new Error("Storage did not provide an upload destination.")
      }
    }
    state.transferred = true
  }
  onProgress("finalizing", file.size)
  return uploadAction<T>({ action: "finish", uploadId, googleApiKey }, signal)
}

export function discardPdfUpload(uploadId: string) {
  return uploadAction({ action: "cancel", uploadId }).catch(() => undefined)
}

export async function uploadInParallel<T>(items: T[], upload: (item: T) => Promise<void>) {
  let next = 0
  const consume = async () => {
    while (next < items.length) {
      const item = items[next++]
      await upload(item)
    }
  }
  await Promise.all(Array.from({ length: Math.min(2, items.length) }, consume))
}
