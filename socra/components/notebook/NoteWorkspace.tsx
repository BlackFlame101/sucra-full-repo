"use client"

import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from "react"
import { MoreHorizontal, Printer, Star, Trash2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { NoteEditor, type EditorHandle, type SelectionRequest, type Spelling } from "./NoteEditor"
import { notebookDraftKey, useNotebookAutosave } from "@/hooks/useNotebookAutosave"
import { readNoteDocument } from "@/lib/notebook/document"
import { isEducationalDocument } from "@/lib/educational-document"
import type { Note, NoteCourse, NoteDraft } from "@/lib/notebook/notes"

export type NoteWorkspaceHandle = EditorHandle & { leave: () => Promise<boolean>; save: () => Promise<boolean> }

function fromNote(note: Note): NoteDraft {
  return { title: note.title, topic: note.topic, course_id: note.course_id, tags: note.tags ?? [], starred: note.starred ?? false,
    content_json: readNoteDocument(note.content_json, note.content, note.source_type !== "manual") }
}

export function NoteWorkspace({ note, courses, onSaved, onDelete, onAsk, onSelectionRequest, handle }: {
  note: Note
  courses: NoteCourse[]
  onSaved: (note: Note) => void
  onDelete: () => void
  onAsk: () => void
  onSelectionRequest: (request: SelectionRequest) => void
  handle: Ref<NoteWorkspaceHandle>
}) {
  const [initial, setInitial] = useState(() => fromNote(note))
  const [details, setDetails] = useState(initial)
  const [tag, setTag] = useState("")
  const [addingTag, setAddingTag] = useState(false)
  const [spelling, setSpelling] = useState<Spelling>("auto")
  const [editorRevision, setEditorRevision] = useState(0)
  const [initialized, setInitialized] = useState(false)
  const draft = useRef(initial)
  const restored = useRef(false)
  const editorHandle = useRef<EditorHandle>(null)
  const { change, flush, preserve, restore, resolve, state } = useNotebookAutosave(note, initial, onSaved)
  const source = note.source_data as { explanation?: unknown; initial_note_version?: number } | null
  const educational = isEducationalDocument(source?.explanation) ? source.explanation : null
  const french = educational?.intent.language === "French"

  async function openPrint() {
    const preview = window.open("about:blank", "_blank")
    if (!preview) return
    preview.opener = null
    if (await flush()) preview.location.replace("/api/notebook/" + encodeURIComponent(note.id) + "/print")
    else preview.close()
  }

  useImperativeHandle(handle, () => ({
    leave: async () => await flush() || preserve(),
    save: flush,
    selection: () => editorHandle.current?.selection() ?? null,
    apply: (...args) => editorHandle.current?.apply(...args) ?? false,
  }), [flush, preserve])

  useEffect(() => {
    const task = window.setTimeout(() => {
      if (restored.current) return
      restored.current = true
      try {
        const savedSpelling = localStorage.getItem("socra:notebook:spelling")
        if (savedSpelling === "en" || savedSpelling === "fr" || savedSpelling === "off") setSpelling(savedSpelling)
        const raw = localStorage.getItem(notebookDraftKey(note.user_id, note.id))
        if (!raw) return
        const recovered = JSON.parse(raw) as { draft: NoteDraft; version: number }
        if (recovered.draft?.content_json?.type !== "doc" || !Number.isInteger(recovered.version)) return
        draft.current = recovered.draft
        setDetails(recovered.draft)
        setInitial(recovered.draft)
        setEditorRevision((revision) => revision + 1)
        restore(recovered.draft, recovered.version)
      } catch { /* The server copy remains available if local storage is unavailable. */ }
      finally { setInitialized(true) }
    }, 0)
    return () => window.clearTimeout(task)
  }, [note.id, note.user_id, restore])

  const update = useCallback((fields: Partial<NoteDraft>) => {
    draft.current = { ...draft.current, ...fields }
    change(draft.current)
    if (!("content_json" in fields)) setDetails(draft.current)
  }, [change])
  const updateContent = useCallback((content_json: NoteDraft["content_json"]) => update({ content_json }), [update])
  const save = useCallback(() => { void flush() }, [flush])

  function addTag() {
    const value = tag.trim()
    if (!value || details.tags.length >= 20 || details.tags.some((item) => item.toLocaleLowerCase() === value.toLocaleLowerCase())) return
    update({ tags: [...details.tags, value] })
    setTag("")
    setAddingTag(false)
  }

  function useServerCopy() {
    if (!state.conflict) return
    const current = fromNote(state.conflict)
    draft.current = current
    setDetails(current)
    setInitial(current)
    setEditorRevision((revision) => revision + 1)
    resolve(false)
  }

  return <div className="flex min-h-full flex-col" onKeyDown={(event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); void flush() }
  }}>
    <div className="mx-auto w-full max-w-[50rem] space-y-2 px-5 py-3 sm:px-8">
      <div className="flex items-center gap-1">
        {!educational && <Input aria-label="Note title" value={details.title} placeholder="Untitled note" maxLength={240} disabled={!initialized}
          onChange={(event) => update({ title: event.target.value })}
          className="h-auto min-w-0 flex-1 rounded-none border-0 bg-transparent px-0 py-1 font-serif text-2xl! shadow-none focus-visible:ring-0 dark:bg-transparent sm:text-3xl!" />}
        {educational && <details className="min-w-0 flex-1 text-sm text-muted-foreground">
          <summary className="cursor-pointer">{french ? "Paramètres de la note" : "Note settings"}</summary>
          <Input aria-label="Note title" value={details.title} maxLength={240} disabled={!initialized}
            onChange={(event) => update({ title: event.target.value })} className="mt-2" />
        </details>}
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Note actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onAsk}>Ask Socra</DropdownMenuItem>
            <DropdownMenuItem disabled={!initialized} onSelect={() => update({ starred: !details.starred })}><Star />{details.starred ? "Unstar note" : "Star note"}</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void flush()}>Save now</DropdownMenuItem>
            {educational && <DropdownMenuItem onSelect={() => void openPrint()}><Printer />
              {french ? "Exporter en PDF" : "Export PDF"}</DropdownMenuItem>}
            {(["auto", "en", "fr", "off"] as const).map((option) =>
              <DropdownMenuItem key={option} role="menuitemradio" aria-checked={spelling === option} onSelect={() => {
                setSpelling(option)
                try { localStorage.setItem("socra:notebook:spelling", option) } catch { /* Storage is optional. */ }
              }}>{spelling === option ? "✓ " : ""}Spellcheck · {{ auto: "Automatic", en: "English", fr: "French", off: "Off" }[option]}</DropdownMenuItem>)}
            <DropdownMenuItem onSelect={onDelete}><Trash2 />Delete note</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <select aria-label="Associated course" value={details.course_id ?? ""} disabled={!initialized} className="max-w-44 rounded-md border bg-card p-1.5 text-foreground"
            onChange={(event) => update({ course_id: event.target.value || null })}>
            <option value="">Personal</option>
            {courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}
          </select>
        <p role="status" className={state.label === "Error" ? "text-destructive" : "text-muted-foreground"}><span aria-hidden className="mr-1 inline-block size-1.5 rounded-full bg-current" />{state.label}</p>
        {educational && <span className="text-muted-foreground">
          {note.version === source?.initial_note_version ? (french ? "Document généré" : "Generated document")
            : (french ? "Révision modifiée " : "Edited revision ") + note.version}
        </span>}
        {details.tags.map((item) => <button type="button" key={item} onClick={() => update({ tags: details.tags.filter((tag) => tag !== item) })}
          className="inline-flex items-center gap-1 rounded-full bg-secondary/15 px-2 py-1 text-xs text-foreground"
          aria-label={`Remove tag ${item}`}>#{item}<X className="size-3" /></button>)}
        {addingTag ? <form className="flex items-center gap-1" onSubmit={(event) => { event.preventDefault(); addTag() }}>
          <Input className="h-7 w-24 text-xs" maxLength={40} value={tag} aria-label="New tag" placeholder="Add tag"
            autoFocus onKeyDown={(event) => { if (event.key === "Escape") setAddingTag(false) }}
            onChange={(event) => setTag(event.target.value)} />
          {tag.trim() && <Button type="submit" variant="ghost" size="sm">Add</Button>}
        </form> : <Button variant="ghost" size="sm" className="h-7 text-xs" disabled={!initialized || details.tags.length >= 20}
          onClick={() => setAddingTag(true)}>Add tag</Button>}
      </div>
      {state.error && <div className="rounded-lg border border-destructive/30 p-3 text-sm" role="alert">
        <p className="text-destructive">{state.error}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {state.conflict ? <>
            <Button size="sm" variant="outline" onClick={useServerCopy}>Use server version</Button>
            <Button size="sm" onClick={() => {
              if (window.confirm("Replace the server version with this draft?")) resolve(true)
            }}>Keep my draft</Button>
          </> : <Button size="sm" variant="outline" onClick={() => void flush()}>Retry save</Button>}
        </div>
      </div>}
    </div>
    {initialized && <NoteEditor key={editorRevision} initial={initial.content_json} onChange={updateContent} onSave={save}
      handle={editorHandle} onSelectionRequest={onSelectionRequest} spelling={spelling} />}
  </div>
}
