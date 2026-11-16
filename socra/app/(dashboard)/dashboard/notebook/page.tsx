"use client"

import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"
import { BookOpen, FileText, PanelRightClose, Plus, Search, Star } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PdfCitation } from "@/components/documents/PdfCitation"
import { NoteWorkspace, type NoteWorkspaceHandle } from "@/components/notebook/NoteWorkspace"
import { NotebookStudy } from "@/components/notebook/NotebookStudy"
import type { SelectionRequest } from "@/components/notebook/NoteEditor"
import { notebookDraftKey } from "@/hooks/useNotebookAutosave"
import { groupNotes, searchNotes, type Note, type NoteCourse, type NoteFilter } from "@/lib/notebook/notes"
import { emptyNote } from "@/lib/notebook/document"

const filters: NoteFilter[] = ["All", "Courses", "Personal", "Starred"]

export default function NotebookPage() {
  const [notes, setNotes] = useState<Note[]>([])
  const [courses, setCourses] = useState<NoteCourse[]>([])
  const [selectedId, setSelectedId] = useState<string>()
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<NoteFilter>("All")
  const [mobile, setMobile] = useState<"notes" | "editor" | "context">("notes")
  const [assistantOpen, setAssistantOpen] = useState(true)
  const [notesOpen, setNotesOpen] = useState(true)
  const [tab, setTab] = useState("sources")
  const [mode, setMode] = useState<"writing" | "chat" | "expanded">("writing")
  const [selectionRequest, setSelectionRequest] = useState<SelectionRequest>()
  const [dueOnly, setDueOnly] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const workspace = useRef<NoteWorkspaceHandle>(null)
  const operation = useRef(false)
  const editorScroll = useRef<HTMLDivElement>(null)
  const assistantHeading = useRef<HTMLHeadingElement>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError("")
    try {
      const response = await fetch("/api/notebook", { signal })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error || "Could not load your notebook.")
      if (signal?.aborted) return
      try {
        setAssistantOpen(localStorage.getItem("socra:notebook:assistant") !== "closed")
        setNotesOpen(localStorage.getItem("socra:notebook:notes") !== "closed")
      } catch { /* Panel preferences are optional. */ }
      setNotes(payload.notes)
      setCourses(payload.courses)
      const requested = new URLSearchParams(location.search).get("note")
      setSelectedId(payload.notes.find((note: Note) => note.id === requested)?.id ?? payload.notes[0]?.id)
      if (requested) setMobile("editor")
    } catch (error) {
      if (!signal?.aborted) setError(error instanceof Error ? error.message : "Could not load your notebook.")
    } finally { if (!signal?.aborted) setLoading(false) }
  }, [])

  function panelPreference(panel: "notes" | "assistant", open: boolean) {
    if (panel === "notes") setNotesOpen(open)
    else setAssistantOpen(open)
    try { localStorage.setItem("socra:notebook:" + panel, open ? "open" : "closed") } catch { /* Storage is optional. */ }
  }

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  const selected = notes.find((note) => note.id === selectedId)
  const onSaved = useCallback((note: Note) => {
    setNotes((current) => [note, ...current.filter((item) => item.id !== note.id)].sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
  }, [])
  const onReview = useCallback((id: string, date: string | null) => {
    setNotes((current) => current.map((note) => note.id === id ? { ...note, review_due: date } : note))
  }, [])
  const handleSelectionRequest = useCallback((request: SelectionRequest) => {
    setSelectionRequest(request)
    const chat = request.action === "ask" || request.action === "explain"
    setTab(chat ? "ask" : "tools")
    if (chat) {
      setMode((current) => current === "expanded" ? current : "chat")
      setMobile("context")
    }
  }, [])
  const clearSelectionRequest = useCallback(() => setSelectionRequest(undefined), [])

  function open(id?: string) {
    setMode("writing")
    setTab("sources")
    setSelectionRequest(undefined)
    if (editorScroll.current) editorScroll.current.scrollTop = 0
    setSelectedId(id)
    setMobile(id ? "editor" : "notes")
    const url = new URL(location.href)
    if (id) url.searchParams.set("note", id)
    else url.searchParams.delete("note")
    window.history.replaceState(null, "", url)
  }

  async function run(action: () => Promise<void>, leave = true) {
    if (operation.current) return
    operation.current = true
    setBusy(true)
    setError("")
    try {
      if (leave && workspace.current && !await workspace.current.leave()) throw new Error("Save or resolve the current draft first.")
      await action()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Notebook request failed.")
    } finally { operation.current = false; setBusy(false) }
  }

  function create() {
    void run(async () => {
      const response = await fetch("/api/notebook", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "Untitled note", content_json: emptyNote, course_id: null }) })
      const note = await response.json()
      if (!response.ok) throw new Error(note.error || "Could not create a note.")
      onSaved(note)
      setFilter("All")
      setDueOnly(false)
      setQuery("")
      open(note.id)
    })
  }

  function remove(note: Note) {
    if (!window.confirm('Delete "' + note.title + '" and its saved sources?')) return
    void run(async () => {
      const response = await fetch("/api/notebook/" + note.id, { method: "DELETE" })
      if (!response.ok) throw new Error("Could not delete this note.")
      try { localStorage.removeItem(notebookDraftKey(note.user_id, note.id)) } catch { /* Storage is optional. */ }
      setNotes((current) => current.filter((item) => item.id !== note.id))
      open(notes.find((item) => item.id !== note.id)?.id)
    }, false)
  }

  const now = new Date()
  const today = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("-")
  const isDue = (note: Note) => !!note.review_due && note.review_due <= today
  const groups = groupNotes(searchNotes(dueOnly ? notes.filter(isDue) : notes, courses, query, filter))
  const courseName = (note: Note) => courses.find((course) => course.id === note.course_id)?.name ?? (note.course_id ? "Course" : "Personal")
  const chatting = mode !== "writing"
  function openChat() {
    setMode((current) => current === "expanded" ? current : "chat")
    setTab("ask")
    setMobile("context")
    if (!chatting) requestAnimationFrame(() => assistantHeading.current?.focus({ preventScroll: true }))
  }
  function returnToWriting(close = false) {
    setMode("writing")
    setTab("sources")
    setMobile("editor")
    if (close) panelPreference("assistant", false)
    requestAnimationFrame(() => editorScroll.current?.focus({ preventScroll: true }))
  }

  return <div className="mx-auto flex h-full min-h-0 max-w-[1800px] flex-col gap-3 p-3 md:p-4">
    {!chatting && <div className="flex shrink-0 flex-wrap items-center gap-2" role="group" aria-label="Notebook panels">
      {(["notes", "editor", "context"] as const).map((panel) => <Button key={panel} type="button" size="sm" className="min-[1200px]:hidden"
        variant={mobile === panel ? "secondary" : "outline"} aria-pressed={mobile === panel}
        onClick={() => { setMobile(panel); if (panel === "context") setAssistantOpen(true) }}>
        {panel === "notes" ? "Notes" : panel === "editor" ? "Editor" : "Study panel"}
      </Button>)}
      <Button className="hidden min-[1200px]:inline-flex" size="sm" variant="outline" aria-pressed={notesOpen}
        onClick={() => panelPreference("notes", !notesOpen)}>Notes</Button>
      <Button className="hidden min-[1200px]:inline-flex" size="sm" variant="outline" aria-pressed={assistantOpen}
        onClick={() => panelPreference("assistant", !assistantOpen)}>Study panel</Button>
      <Button size="sm" variant="secondary" disabled={!selected} onClick={openChat}>Ask Socra</Button>
    </div>}
    {error && <div role="alert" className="flex shrink-0 items-center gap-2 rounded-lg border border-destructive/30 p-2 text-sm text-destructive">
      {error}{!notes.length && <Button size="sm" variant="ghost" onClick={() => void load()}>Reload</Button>}
    </div>}
    <div className={"grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] grid-cols-[minmax(0,1fr)] gap-3 " + (chatting
      ? mode === "chat" ? "min-[1100px]:grid-cols-[minmax(0,1.12fr)_minmax(0,1fr)]" : ""
      : notesOpen
      ? assistantOpen ? "min-[1200px]:grid-cols-[minmax(14rem,1fr)_minmax(0,2.8fr)_minmax(16rem,1.2fr)]"
        : "min-[1200px]:grid-cols-[minmax(14rem,1fr)_minmax(0,3.5fr)]"
      : assistantOpen ? "min-[1200px]:grid-cols-[minmax(0,3.5fr)_minmax(16rem,1fr)]" : "")}>
      <aside aria-label="Notes" className={(chatting ? "hidden" : (mobile === "notes" ? "flex" : "hidden") + (notesOpen ? " min-[1200px]:flex" : " min-[1200px]:hidden")) + " min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-card/40"}>
        <div className="space-y-4 border-b p-4">
          <div className="flex items-center justify-between gap-2">
            <h1 className="font-serif text-2xl">Notebook</h1>
            <Button type="button" size="sm" onClick={create} disabled={loading || busy}><Plus />New note</Button>
          </div>
          <div className="relative"><Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" aria-label="Search notes" placeholder="Search notes…" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
          <div className="flex items-center justify-between gap-1" role="group" aria-label="Filter notes">
            <select aria-label="Note category" value={filter} onChange={(event) => setFilter(event.target.value as NoteFilter)}
              className="min-w-0 flex-1 rounded-md border bg-card px-2 py-1 text-xs">
              {filters.map((item) => <option key={item}>{item}</option>)}
            </select>
            <Button size="sm" variant={dueOnly ? "secondary" : "ghost"} aria-pressed={dueOnly}
              onClick={() => setDueOnly(!dueOnly)} className="h-7 px-2 text-xs">Due ({notes.filter(isDue).length})</Button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2">
          {loading ? <p className="p-3 text-sm text-muted-foreground" role="status">Loading notes…</p>
            : groups.every(([, group]) => !group.length) ? <p className="p-3 text-sm text-muted-foreground">{notes.length ? "No notes match." : "No notes yet."}</p>
            : groups.map(([heading, group]) => group.length > 0 && <section key={heading} className="mb-3">
              <h2 className="px-3 py-1.5 text-xs font-medium text-muted-foreground">{heading}</h2>
              {group.map((note) => <button key={note.id} type="button" aria-current={note.id === selectedId ? "true" : undefined}
                disabled={busy} onClick={() => note.id === selectedId ? setMobile("editor") : void run(async () => open(note.id))}
                className={"mb-1 flex w-full min-w-0 items-start gap-2 rounded-lg border px-3 py-2.5 text-left " +
                  (note.id === selectedId ? "border-secondary/40 bg-secondary/15" : "border-transparent hover:bg-muted/50")}>
                <FileText className="mt-0.5 size-4 shrink-0 text-secondary" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{note.title}</span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">{note.content.replace(/\s+/g, " ").trim() || "Empty note"}</span>
                  {isDue(note) && <span className="block text-xs text-tertiary">Review due</span>}
                  <span className="mt-1 block truncate text-[11px] text-muted-foreground">{courseName(note)} · {new Date(note.updated_at).toLocaleDateString()}</span>
                </span>
                {note.starred && <Star className="mt-0.5 size-3.5 shrink-0 fill-tertiary text-tertiary" aria-label="Starred" />}
              </button>)}
            </section>)}
        </div>
      </aside>
      <section aria-label="Note editor" className={(chatting ? mode === "chat" ? "hidden min-[1100px]:flex" : "hidden" : (mobile === "editor" ? "flex" : "hidden") + " min-[1200px]:flex") + " relative min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-card/30"}>
        <div ref={editorScroll} tabIndex={-1} data-notebook-editor-scroll className="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain">
          {selected ? <NoteWorkspace key={selected.id} note={selected} courses={courses} onSaved={onSaved}
            onDelete={() => remove(selected)} onAsk={openChat}
            onSelectionRequest={handleSelectionRequest} handle={workspace} />
            : <div className="grid h-full place-content-center gap-3 p-6 text-center text-muted-foreground">
              <BookOpen className="mx-auto size-8" /><p>{loading ? "Loading notebook…" : "Select a note or create a new one."}</p>
            </div>}
        </div>
      </section>
      <aside aria-label="Study panel" className={(chatting ? "flex" : !assistantOpen ? "hidden" : mobile === "context" ? "flex" : "hidden min-[1200px]:flex") + " min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-card/40 [overflow-wrap:anywhere]"}>
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-1 border-b px-3 py-2 sm:px-4">
          <h2 ref={assistantHeading} tabIndex={-1} className="font-serif text-lg">Socra Assistant</h2>
          <div className="flex flex-wrap items-center gap-1">
          {chatting && <>
            <Button size="sm" variant="ghost" onClick={() => returnToWriting()}>Writing mode</Button>
            <Button size="sm" variant="outline" className="hidden min-[1100px]:inline-flex"
              onClick={() => setMode(mode === "expanded" ? "chat" : "expanded")}>{mode === "expanded" ? "Collapse Chat" : "Expand Chat"}</Button>
          </>}
          <Button size="icon-sm" variant="ghost" aria-label="Close study panel"
            onClick={() => returnToWriting(true)}><PanelRightClose /></Button>
          </div>
        </div>
        <Tabs activationMode="manual" value={tab} onValueChange={(value) => value === "ask" ? openChat() : setTab(value)}
          className="min-h-0 min-w-0 flex-1 gap-0">
          <TabsList className="mx-3 my-2 grid w-auto shrink-0 grid-cols-3">
            <TabsTrigger value="ask" className="text-xs">Ask Socra</TabsTrigger>
            <TabsTrigger value="tools" className="text-xs">Study Tools</TabsTrigger>
            <TabsTrigger value="sources" className="text-xs">Sources</TabsTrigger>
          </TabsList>
          <TabsContent value="sources" className="min-h-0 overflow-y-auto overscroll-contain p-3">{selected ? <NoteSources key={selected.id} note={selected} courseName={courseName(selected)} />
            : <p className="p-2 text-sm text-muted-foreground">Select a note to see its sources.</p>}</TabsContent>
          {selected && <NotebookStudy key={selected.id} note={selected} workspace={workspace} tab={tab}
            selectionRequest={selectionRequest} onSelectionHandled={clearSelectionRequest}
            onReview={onReview} onApplied={() => setMobile("editor")} />}
          {!selected && tab !== "sources" && <TabsContent value={tab}><p className="p-3 text-sm text-muted-foreground">Select a note to use Socra.</p></TabsContent>}
        </Tabs>
      </aside>
    </div>
  </div>
}

type Source = { id: string; kind: string; session_id: string | null; message_id: string | null; citations: Array<{ document_id: string; filename: string; page_number: number }> }

function NoteSources({ note, courseName }: { note: Note; courseName: string }) {
  const [sources, setSources] = useState<Source[]>([])
  const [availableDocuments, setAvailableDocuments] = useState<string[]>([])
  const [status, setStatus] = useState("Loading sources…")
  useEffect(() => {
    const controller = new AbortController()
    fetch("/api/notebook/" + note.id + "/sources", { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error()
      const payload = await response.json()
      if (controller.signal.aborted) return
      setSources(payload.sources)
      setAvailableDocuments(payload.availableDocuments ?? [])
      setStatus("")
    }).catch(() => { if (!controller.signal.aborted) setStatus("Could not load saved sources.") })
    return () => controller.abort()
  }, [note.id])
  const legacy = note.source_data as { session_id?: string } | null
  return <div className="space-y-2 p-1 text-sm">
    {note.course_id && <Link className="block rounded-lg border p-2 text-secondary hover:underline"
      href={"/dashboard/course/" + note.course_id}>{courseName}</Link>}
    {note.source_document_id && note.source_page && <div className="rounded-lg border p-2"><PdfCitation documentId={note.source_document_id}
      page={note.source_page} filename={note.source_filename ?? "Original PDF"} /></div>}
    {note.course_id && legacy?.session_id && /^[a-f0-9-]{36}$/i.test(legacy.session_id) &&
      <Link className="block rounded-lg border p-2 text-secondary hover:underline"
        href={"/dashboard/course/" + note.course_id + "/inquiry/" + legacy.session_id}>Original Socra inquiry</Link>}
    {sources.map((source) => <div key={source.id} className="space-y-2 rounded-lg border p-2">
      {source.session_id && source.message_id
        ? <a href={"/api/notebook/source/" + source.id} className="text-secondary hover:underline">Open original {source.kind}</a>
        : <p className="text-muted-foreground">Original response unavailable</p>}
      {source.citations.map((citation) => <div key={citation.document_id + ":" + citation.page_number}>
        {availableDocuments.includes(citation.document_id)
          ? <PdfCitation documentId={citation.document_id} page={citation.page_number} filename={citation.filename} />
          : <p className="text-muted-foreground">{citation.filename} · page {citation.page_number} (unavailable)</p>}</div>)}
    </div>)}
    {status ? <p role="status" className="text-muted-foreground">{status}</p>
      : !sources.length && !note.course_id && !note.source_document_id && <p className="text-muted-foreground">No sources linked.</p>}
  </div>
}
