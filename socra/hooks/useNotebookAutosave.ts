"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import type { Note, NoteDraft } from "@/lib/notebook/notes"

export function notebookDraftKey(owner: string, id: string) { return `socra:notebook:${owner}:${id}` }
type SaveState = { label: "Saved" | "Saving" | "Unsaved" | "Error"; error?: string; conflict?: Note }

export function useNotebookAutosave(note: Note, initial: NoteDraft, onSaved: (note: Note) => void) {
  const [state, setState] = useState<SaveState>({ label: "Saved" })
  const key = notebookDraftKey(note.user_id, note.id)
  const url = `/api/notebook/${note.id}`
  const draft = useRef(initial)
  const version = useRef(note.version ?? 1)
  const changed = useRef(0)
  const saved = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const pending = useRef<Promise<boolean> | null>(null)
  const conflict = useRef<Note | null>(null)
  const alive = useRef(true)
  const storedDraft = useRef<string | null>(null)

  const preserve = useCallback(() => {
    try {
      if (changed.current !== saved.current) {
        const value = JSON.stringify({ version: version.current, draft: draft.current })
        localStorage.setItem(key, value)
        storedDraft.current = value
      } else if (storedDraft.current && localStorage.getItem(key) === storedDraft.current) {
        localStorage.removeItem(key)
        storedDraft.current = null
      }
      return true
    } catch { return false }
  }, [key])

  const flush = useCallback(async (): Promise<boolean> => {
    clearTimeout(timer.current)
    while (changed.current !== saved.current) {
      if (conflict.current) return false
      if (!pending.current) {
        const sequence = changed.current
        const snapshot = draft.current
        const baseVersion = version.current
        if (alive.current) setState({ label: "Saving" })
        pending.current = (async () => {
          try {
            const response = await fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ...snapshot, title: snapshot.title.trim() || "Untitled note", version: baseVersion }) })
            const payload = await response.json()
            if (response.status === 409 && payload.note) {
              conflict.current = payload.note
              if (alive.current) setState({ label: "Error", error: "This note changed elsewhere. Choose which version to keep.", conflict: payload.note })
              return false
            }
            if (!response.ok) throw new Error(payload.error || "Could not save this note.")
            version.current = payload.version
            saved.current = sequence
            preserve()
            if (alive.current) {
              onSaved(payload)
              setState({ label: sequence === changed.current ? "Saved" : "Unsaved" })
            }
            return true
          } catch (error) {
            if (alive.current) setState({ label: "Error", error: error instanceof Error ? error.message : "Could not save this note." })
            return false
          } finally { pending.current = null }
        })()
      }
      if (!await pending.current) return false
    }
    return true
  }, [onSaved, preserve, url])

  const change = useCallback((next: NoteDraft) => {
    draft.current = next
    changed.current++
    preserve()
    if (conflict.current) return
    if (!pending.current) setState({ label: "Unsaved" })
    clearTimeout(timer.current)
    timer.current = setTimeout(() => void flush(), 700)
  }, [flush, preserve])

  const restore = useCallback((next: NoteDraft, baseVersion: number) => {
    if (baseVersion !== version.current) {
      conflict.current = note
      setState({ label: "Error", error: "A recovered draft is based on an older version.", conflict: note })
      version.current = baseVersion
    }
    change(next)
  }, [change, note])

  const resolve = useCallback((keepDraft: boolean) => {
    const current = conflict.current
    if (!current) return
    version.current = current.version
    conflict.current = null
    if (keepDraft) {
      preserve()
      void flush()
    }
    else {
      saved.current = changed.current
      preserve()
      onSaved(current)
      setState({ label: "Saved" })
    }
  }, [flush, onSaved, preserve])

  useEffect(() => {
    alive.current = true
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (changed.current === saved.current) return
      preserve()
      event.preventDefault()
      event.returnValue = ""
    }
    window.addEventListener("beforeunload", beforeUnload)
    return () => {
      alive.current = false
      clearTimeout(timer.current)
      window.removeEventListener("beforeunload", beforeUnload)
    }
  }, [preserve])

  return { change, flush, preserve, resolve, restore, state }
}
