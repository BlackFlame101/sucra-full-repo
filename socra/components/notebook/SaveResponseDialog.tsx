"use client"

import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"

export type CaptureTarget = { messageId: string; title: string; selection: string }
type Destination = { id: string; title: string }

export function SaveResponseDialog({ target, courseId, sessionId, onClose, onSaved }: {
  target: CaptureTarget
  courseId: string
  sessionId: string
  onClose: () => void
  onSaved: (id: string) => void
}) {
  const [destination, setDestination] = useState("new")
  const [title, setTitle] = useState(target.title)
  const [selectionOnly, setSelectionOnly] = useState(Boolean(target.selection))
  const [notes, setNotes] = useState<Destination[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const busy = useRef(false)
  const requests = useRef(new Map<string, string>())

  useEffect(() => {
    const controller = new AbortController()
    fetch("/api/notebook?view=picker", { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error()
      const payload = await response.json()
      if (!controller.signal.aborted) setNotes(payload.notes)
    }).catch(() => { if (!controller.signal.aborted) setLoadError(true) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  async function save() {
    if (busy.current) return
    busy.current = true
    setSaving(true)
    setError("")
    const key = JSON.stringify([destination, selectionOnly])
    const requestId = requests.current.get(key) ?? crypto.randomUUID()
    requests.current.set(key, requestId)
    try {
      const response = await fetch("/api/notebook/capture", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId, course_id: courseId, session_id: sessionId, message_id: target.messageId,
          note_id: destination === "new" ? null : destination, title,
          selection: selectionOnly ? target.selection : null }) })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error || "Could not save to Notebook.")
      onSaved(result.id)
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save to Notebook.") }
    finally { busy.current = false; setSaving(false) }
  }

  return <Dialog open onOpenChange={(open) => { if (!open && !busy.current) onClose() }}>
    <DialogContent onEscapeKeyDown={(event) => { if (busy.current) event.preventDefault() }}
      onPointerDownOutside={(event) => { if (busy.current) event.preventDefault() }}>
      <DialogHeader><DialogTitle>Save to Notebook</DialogTitle>
        <DialogDescription>Keep this response with a link back to the original inquiry.</DialogDescription></DialogHeader>
      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void save() }}>
        <label className="block space-y-1 text-sm"><span>Destination</span>
          <select value={destination} onChange={(event) => setDestination(event.target.value)} disabled={saving}
            className="block w-full rounded-md border bg-card p-2">
            <option value="new">Create a new note</option>
            {notes.map((note) => <option key={note.id} value={note.id}>Append to {note.title}</option>)}
          </select>
        </label>
        {loading && <p role="status" className="text-xs text-muted-foreground">Loading existing notes…</p>}
        {loadError && <p role="status" className="text-xs text-muted-foreground">Existing notes could not be loaded.</p>}
        {destination === "new" && <label className="block space-y-1 text-sm"><span>Note title</span>
          <Input value={title} maxLength={240} required disabled={saving} onChange={(event) => setTitle(event.target.value)} /></label>}
        {target.selection && <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={selectionOnly} disabled={saving} onChange={(event) => setSelectionOnly(event.target.checked)} />
          Save highlighted text only</label>}
        {selectionOnly && <blockquote className="max-h-24 overflow-auto rounded-md border p-2 text-xs text-muted-foreground">{target.selection}</blockquote>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter><Button type="button" variant="outline" disabled={saving} onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={saving}>{saving ? "Saving…" : destination === "new" ? "Create note" : "Append to note"}</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
}
