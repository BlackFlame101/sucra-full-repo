"use client"

import { EditorContent, useEditor } from "@tiptap/react"
import type { JSONContent } from "@tiptap/react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { suggestionNote } from "@/lib/notebook/document"
import { notebookExtensions } from "@/lib/notebook/schema"
import type { EditAnchor, EditPlacement } from "./NoteEditor"

function ReviewContent({ content }: { content: JSONContent }) {
  const editor = useEditor({ extensions: notebookExtensions, content, editable: false,
    immediatelyRender: false, editorProps: { attributes: { class: "notebook-prose" } } })
  return <EditorContent editor={editor} />
}

export function EditReview({ anchor, suggestion, busy, status, onApply, onRegenerate, onDiscard, onCloseFocus }: {
  anchor: EditAnchor | null; suggestion: string; busy: boolean; status: string
  onApply: (placement: EditPlacement) => void; onRegenerate: () => void; onDiscard: () => void; onCloseFocus: () => void
}) {
  const original = anchor && (anchor.text.trim() ? anchor.document.slice(anchor.from, anchor.to).content.toJSON() : anchor.document.toJSON().content)
  const long = Math.max(anchor?.text.length || (anchor?.document.textContent.length ?? 0), suggestion.length) > 1500
  return <Dialog open onOpenChange={(open) => { if (!open) onDiscard() }}>
    <DialogContent className="flex max-h-[min(88dvh,56rem)] w-[calc(100%-1rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-6xl"
      onCloseAutoFocus={(event) => { event.preventDefault(); onCloseFocus() }}>
      <DialogHeader className="shrink-0 border-b px-5 py-4 pr-12">
        <DialogTitle className="font-serif text-2xl">Review Socra’s edit</DialogTitle>
        <DialogDescription>{anchor?.text.trim() ? "Compare the selected passage with the suggestion." : "Compare your note with the suggestion."}</DialogDescription>
      </DialogHeader>
      <div className={"grid min-h-0 flex-1 overflow-y-auto md:grid-cols-2 md:overflow-hidden " + (long ? "h-[60dvh]" : "")}>
        <section aria-label="Original" tabIndex={0} className="min-h-0 min-w-0 border-b p-5 md:overflow-y-auto md:border-r md:border-b-0">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Original</h3>
          {original?.length ? <ReviewContent content={{ type: "doc", content: original }} />
            : <p className="text-sm text-muted-foreground">No original text.</p>}
        </section>
        <section aria-label="Suggested" tabIndex={0} className="min-h-0 min-w-0 p-5 md:overflow-y-auto">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-secondary">Suggested</h3>
          {suggestion && <ReviewContent key={suggestion} content={suggestionNote(suggestion)} />}
          {status && <p role={busy ? "status" : "alert"} className="mt-3 text-sm text-muted-foreground">{status}</p>}
        </section>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2 border-t bg-card px-5 py-3">
        <Button size="sm" disabled={busy || !suggestion || !anchor?.text.trim()} onClick={() => onApply("replace")}>Replace selection</Button>
        <Button size="sm" variant="outline" disabled={busy || !suggestion || !anchor} onClick={() => onApply("below")}>Insert below</Button>
        <Button size="sm" variant="outline" disabled={busy || !suggestion} onClick={() => onApply("end")}>Add to end</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={onRegenerate}>Regenerate</Button>
        <Button size="sm" variant="ghost" onClick={onDiscard}>Discard</Button>
      </div>
    </DialogContent>
  </Dialog>
}
