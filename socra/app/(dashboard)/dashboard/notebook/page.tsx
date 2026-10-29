"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { BookOpen, FilePlus2, Save, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

type Course = { id: string; name: string }
type Note = { id: string; course_id: string | null; course_name: string; title: string; topic: string; content: string; source_type: "manual" | "explanation" | "exercise"; source_data: Record<string, unknown>; source_document_id: string | null; source_page: number | null; source_filename?: string; updated_at: string }

export default function NotebookPage() {
  const [notes, setNotes] = useState<Note[]>([])
  const [courses, setCourses] = useState<Course[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [title, setTitle] = useState("")
  const [topic, setTopic] = useState("")
  const [content, setContent] = useState("")
  const [courseId, setCourseId] = useState("personal")
  const [noteQuery, setNoteQuery] = useState("")
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const selectedNote = notes.find((note) => note.id === selectedId) ?? null
  const visibleNotes = notes.filter((note) => `${note.title} ${note.topic} ${note.course_name}`.toLocaleLowerCase().includes(noteQuery.trim().toLocaleLowerCase()))
  const sourceSessionId = typeof selectedNote?.source_data?.session_id === "string" ? selectedNote.source_data.session_id : null

  async function load(selectId?: string | null) {
    setLoading(true)
    const response = await fetch("/api/notebook")
    const payload = await response.json()
    if (!response.ok) setError(payload.error || "Could not load your notebook.")
    else {
      setNotes(payload.notes)
      setCourses(payload.courses)
      const nextId = selectId ?? selectedId
      const next = payload.notes.find((note: Note) => note.id === nextId) ?? payload.notes[0] ?? null
      setSelectedId(next?.id ?? null)
      setTitle(next?.title ?? "")
      setTopic(next?.topic ?? "")
      setContent(next?.content ?? "")
      setCourseId(next?.course_id ?? "personal")
      setError("")
    }
    setLoading(false)
  }
  useEffect(() => { void load(null) }, [])

  function selectNote(note: Note) {
    setSelectedId(note.id)
    setTitle(note.title)
    setTopic(note.topic)
    setContent(note.content)
    setCourseId(note.course_id ?? "personal")
  }

  function newNote() {
    setSelectedId(null)
    setTitle("")
    setTopic("")
    setContent("")
    setCourseId("personal")
  }

  async function saveNote() {
    if (!title.trim()) { setError("Give your note a title first."); return }
    setSaving(true)
    const url = selectedId ? `/api/notebook/${selectedId}` : "/api/notebook"
    const response = await fetch(url, {
      method: selectedId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, topic, content, ...(selectedId ? {} : { course_id: courseId === "personal" ? null : courseId }) }),
    })
    const payload = await response.json()
    if (!response.ok) setError(payload.error || "Could not save your note.")
    else { await load(payload.id ?? selectedId); setError("") }
    setSaving(false)
  }

  async function deleteNote() {
    if (!selectedId) return
    const response = await fetch(`/api/notebook/${selectedId}`, { method: "DELETE" })
    if (!response.ok) { const payload = await response.json(); setError(payload.error || "Could not delete this note."); return }
    setNotes((current) => current.filter((note) => note.id !== selectedId))
    newNote()
    setError("")
  }

  return <div className="container mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-12">
    <div className="mb-8"><p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-secondary">Your learning workspace</p><h1 className="font-serif text-3xl font-medium sm:text-4xl">Notebook</h1><p className="mt-2 max-w-2xl text-sm text-muted-foreground">Keep your own notes and turn useful course explanations into something you can revisit.</p></div>
    {error && <p role="alert" className="mb-5 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    <div className="grid min-h-[620px] gap-5 lg:grid-cols-[300px_1fr]">
      <aside className="rounded-xl border border-border/60 bg-card/40 p-3"><div className="mb-3 flex items-center justify-between px-2 py-1"><h2 className="font-medium">Notes</h2><Button type="button" size="sm" variant="outline" className="gap-1.5" onClick={newNote}><FilePlus2 className="h-4 w-4"/>New</Button></div><Input value={noteQuery} onChange={(event) => setNoteQuery(event.target.value)} placeholder="Search title, topic, course…" aria-label="Search notes" className="mb-3"/>{loading ? <p className="p-3 text-sm text-muted-foreground">Loading notes…</p> : visibleNotes.length ? <div className="space-y-1">{visibleNotes.map((note) => <button key={note.id} type="button" onClick={() => selectNote(note)} className={`w-full rounded-lg p-3 text-left transition ${selectedId === note.id ? "bg-secondary/10" : "hover:bg-muted/60"}`}><span className="block truncate text-sm font-medium">{note.title}</span><span className="mt-1 block truncate text-xs text-muted-foreground">{note.topic ? `${note.topic} · ` : ""}{note.course_name} · {new Date(note.updated_at).toLocaleDateString()}</span></button>)}</div> : <div className="p-3 text-sm text-muted-foreground">{notes.length ? "No notes match your search." : "No notes yet. Start one here or save an explanation from a chat."}</div>}</aside>
      <section className="rounded-xl border border-border/60 bg-card/40 p-5 sm:p-7"><div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2 text-secondary"><BookOpen className="h-5 w-5"/><span className="text-sm font-medium">{selectedNote ? selectedNote.course_name : "New note"}</span></div><div className="flex gap-2">{selectedId && <Button type="button" size="sm" variant="ghost" className="gap-1.5 text-destructive" onClick={() => void deleteNote()}><Trash2 className="h-4 w-4"/>Delete</Button>}<Button type="button" size="sm" className="gap-1.5" onClick={() => void saveNote()} disabled={saving}><Save className="h-4 w-4"/>{saving ? "Saving…" : "Save note"}</Button></div></div>
        {!selectedId && <div className="mb-5 max-w-xs space-y-2"><label htmlFor="note-course" className="text-sm font-medium">Course</label><Select value={courseId} onValueChange={setCourseId}><SelectTrigger id="note-course"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="personal">Personal note</SelectItem>{courses.map((course) => <SelectItem key={course.id} value={course.id}>{course.name}</SelectItem>)}</SelectContent></Select></div>}
        <div className="space-y-4"><Input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={240} placeholder="Note title" aria-label="Note title" className="border-0 px-0 font-serif text-2xl shadow-none focus-visible:ring-0"/><Input value={topic} onChange={(event) => setTopic(event.target.value)} maxLength={120} placeholder="Topic (for example: RDD transformations)" aria-label="Note topic"/><Textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder="Write your notes here…\n\nYou can save course explanations from a chat to keep them alongside your own notes." className="min-h-[430px] resize-y border-0 px-0 text-sm leading-7 shadow-none focus-visible:ring-0"/>
        {selectedNote?.source_type !== "manual" && selectedNote && <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-4 text-xs text-muted-foreground"><span>Saved from a {selectedNote.source_type}{selectedNote.source_filename ? ` · ${selectedNote.source_filename}` : ""}{selectedNote.source_page ? ` · page ${selectedNote.source_page}` : ""}</span>{selectedNote.course_id && <Link className="font-medium text-secondary hover:underline" href={`/dashboard/course/${selectedNote.course_id}`}>Open course source</Link>}{selectedNote.course_id && sourceSessionId && <Link className="font-medium text-secondary hover:underline" href={`/dashboard/course/${selectedNote.course_id}/inquiry/${sourceSessionId}`}>Open original chat</Link>}</div>}
        </div>
      </section>
    </div>
  </div>
}
