"use client"

import { memo, useEffect, useImperativeHandle, useRef, useState, type Ref } from "react"
import { EditorContent, useEditor, useEditorState, type Editor } from "@tiptap/react"
import { BubbleMenu } from "@tiptap/react/menus"
import { Bold, CheckSquare, Code, Heading1, Heading2, Heading3, Italic, Link2, List, ListOrdered, Quote, Redo2, Sigma, Undo2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { closeHistory } from "@tiptap/pm/history"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { suggestionNote, safeNoteLink, type NoteDocument } from "@/lib/notebook/document"
import { notebookExtensions } from "@/lib/notebook/schema"
import { editRange, type EditAnchor, type EditPlacement } from "@/lib/notebook/edit-range"

export type { EditAnchor, EditPlacement } from "@/lib/notebook/edit-range"
export type SelectionRequest = { anchor: EditAnchor; action: "ask" | "explain" | "simplify" | "improve" | "example" }
const selectionActions = { ask: "Ask Socra", explain: "Explain selection", simplify: "Simplify selection", improve: "Improve writing", example: "Add examples" } as const
export type Spelling = "auto" | "en" | "fr" | "off"
export type EditorHandle = { selection: () => EditAnchor | null; apply: (text: string, placement: EditPlacement, anchor: EditAnchor | null) => boolean }

function capture(editor: Editor): EditAnchor {
  const { selection, doc } = editor.state
  return { from: selection.from, to: selection.to,
    text: doc.textBetween(selection.from, selection.to, "\n", (node) => node.attrs.latex ?? ""), document: doc }
}

export const NoteEditor = memo(function NoteEditor({ initial, onChange, onSave, handle, onSelectionRequest, spelling }: {
  initial: NoteDocument
  onChange: (value: NoteDocument) => void
  onSave: () => void
  handle: Ref<EditorHandle>
  onSelectionRequest: (request: SelectionRequest) => void
  spelling: Spelling
}) {
  const callbacks = useRef({ onChange, onSave })
  useEffect(() => { callbacks.current = { onChange, onSave } }, [onChange, onSave])
  const [insert, setInsert] = useState<"link" | "math" | null>(null)
  const [value, setValue] = useState("")
  const [invalid, setInvalid] = useState(false)
  const [selection, setSelection] = useState({ from: 1, to: 1 })
  const selectionMenu = useRef<HTMLDivElement>(null)
  const dismissed = useRef<EditAnchor | null>(null)
  const editor = useEditor({
    extensions: notebookExtensions, content: initial, immediatelyRender: false, shouldRerenderOnTransaction: false,
    editorProps: {
      attributes: { class: "notebook-editor notebook-prose", role: "textbox", "aria-label": "Note content", "aria-multiline": "true", "aria-keyshortcuts": "Alt+Shift+A" },
      handleKeyDown(_view, event) {
        if (event.altKey && event.shiftKey && event.code === "KeyA" && selectionMenu.current?.getClientRects().length) {
          const first = selectionMenu.current.querySelector("button")
          if (first && getComputedStyle(selectionMenu.current).visibility !== "hidden") {
            event.preventDefault()
            first.focus()
            return true
          }
        }
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
          event.preventDefault()
          callbacks.current.onSave()
          return true
        }
        return false
      },
    },
    onUpdate: ({ editor }) => callbacks.current.onChange(editor.getJSON() as NoteDocument),
  })
  useEffect(() => {
    if (!editor) return
    editor.view.dom.setAttribute("spellcheck", String(spelling !== "off"))
    if (spelling === "en" || spelling === "fr") editor.view.dom.setAttribute("lang", spelling)
    else editor.view.dom.removeAttribute("lang")
    const updateCode = () => editor.view.dom.querySelectorAll("pre, code").forEach((node) => node.setAttribute("spellcheck", "false"))
    updateCode()
    editor.on("update", updateCode)
    return () => { editor.off("update", updateCode) }
  }, [editor, spelling])
  const active = useEditorState({ editor, selector: ({ editor }) => editor ? {
    h1: editor.isActive("heading", { level: 1 }), h2: editor.isActive("heading", { level: 2 }), h3: editor.isActive("heading", { level: 3 }),
    bold: editor.isActive("bold"), italic: editor.isActive("italic"), bullet: editor.isActive("bulletList"),
    ordered: editor.isActive("orderedList"), task: editor.isActive("taskList"), quote: editor.isActive("blockquote"),
    code: editor.isActive("codeBlock"), link: editor.isActive("link"), undo: editor.can().undo(), redo: editor.can().redo(),
  } : null })
  useImperativeHandle(handle, () => ({
    selection: () => {
      if (!editor) return null
      return capture(editor)
    },
    apply: (text, placement, anchor) => {
      if (!editor) return false
      const range = editRange(editor.state.doc, placement, anchor)
      if (range === null) return false
      const transaction = editor.chain().focus().command(({ tr }) => { closeHistory(tr); return true })
      const blocks = suggestionNote(text).content
      if (typeof range !== "number") {
        const sameParagraph = editor.state.doc.resolve(range.from).sameParent(editor.state.doc.resolve(range.to))
        const replacement = sameParagraph && blocks.length === 1 && blocks[0].type === "paragraph" ? blocks[0].content ?? [] : blocks
        return transaction.insertContentAt(range, replacement).run()
      }
      return transaction.insertContentAt(range, blocks).run()
    },
  }), [editor])
  if (!editor) return <p className="px-6 py-4 text-sm text-muted-foreground" role="status">Loading editor…</p>

  function open(kind: "link" | "math", editor: Editor) {
    setSelection({ from: editor.state.selection.from, to: editor.state.selection.to })
    setValue(kind === "link" ? editor.getAttributes("link").href ?? "" : "")
    setInvalid(false)
    setInsert(kind)
  }

  function apply() {
    if (!editor) return
    const text = value.trim()
    if (insert === "link" && text && !safeNoteLink(text) || insert === "math" && !text) { setInvalid(true); return }
    const chain = editor.chain().setTextSelection(selection)
    if (insert === "math") chain.insertBlockMath({ latex: text }).run()
    else if (!text) chain.extendMarkRange("link").unsetLink().run()
    else if (selection.from === selection.to && !editor.isActive("link")) {
      chain.insertContent({ type: "text", text, marks: [{ type: "link", attrs: { href: text } }] }).run()
    } else chain.extendMarkRange("link").setLink({ href: text }).run()
    setInsert(null)
  }

  const controls = [
    { label: "Heading 1", icon: Heading1, active: active?.h1, run: () => editor.chain().focus().toggleHeading({ level: 1 }).run() },
    { label: "Heading 2", icon: Heading2, active: active?.h2, run: () => editor.chain().focus().toggleHeading({ level: 2 }).run() },
    { label: "Heading 3", icon: Heading3, active: active?.h3, run: () => editor.chain().focus().toggleHeading({ level: 3 }).run() },
    { label: "Bold (Ctrl+B)", icon: Bold, active: active?.bold, run: () => editor.chain().focus().toggleBold().run() },
    { label: "Italic (Ctrl+I)", icon: Italic, active: active?.italic, run: () => editor.chain().focus().toggleItalic().run() },
    { label: "Bullet list", icon: List, active: active?.bullet, run: () => editor.chain().focus().toggleBulletList().run() },
    { label: "Numbered list", icon: ListOrdered, active: active?.ordered, run: () => editor.chain().focus().toggleOrderedList().run() },
    { label: "Checklist", icon: CheckSquare, active: active?.task, run: () => editor.chain().focus().toggleTaskList().run() },
    { label: "Quote", icon: Quote, active: active?.quote, run: () => editor.chain().focus().toggleBlockquote().run() },
    { label: "Code block", icon: Code, active: active?.code, run: () => editor.chain().focus().toggleCodeBlock().run() },
    { label: "Link", icon: Link2, active: active?.link, run: () => open("link", editor) },
    { label: "Equation", icon: Sigma, run: () => open("math", editor) },
    { label: "Undo (Ctrl+Z)", icon: Undo2, disabled: !active?.undo, run: () => editor.chain().focus().undo().run() },
    { label: "Redo", icon: Redo2, disabled: !active?.redo, run: () => editor.chain().focus().redo().run() },
  ]

  return <>
    <BubbleMenu editor={editor} ref={selectionMenu} pluginKey="bubbleMenu" updateDelay={120} options={{
      placement: "top", offset: 10, flip: true, shift: { padding: 8 }, hide: true,
      scrollTarget: editor.view.dom.closest<HTMLElement>("[data-notebook-editor-scroll]") ?? undefined,
    }}
      shouldShow={({ editor, element }) => {
        const anchor = capture(editor)
        const previous = dismissed.current
        if (previous && (anchor.from !== previous.from || anchor.to !== previous.to || anchor.document !== previous.document)) dismissed.current = null
        return !!anchor.text.trim() && !dismissed.current && (editor.isFocused || element.contains(document.activeElement))
      }} role="group" aria-label="Actions for selected text"
      onKeyDown={(event) => {
        if (event.key !== "Escape") return
        event.preventDefault()
        event.stopPropagation()
        dismissed.current = capture(editor)
        editor.commands.focus()
        editor.commands.setMeta("bubbleMenu", "hide")
      }}
      className="z-30 flex max-w-[min(28rem,calc(100vw-2rem))] flex-wrap gap-1 rounded-lg border bg-popover p-1 shadow-lg">
      {Object.entries(selectionActions).map(([action, label]) => <Button key={action} size="sm" variant="ghost" type="button"
        onMouseDown={(event) => event.preventDefault()} onClick={() => {
          const anchor = capture(editor)
          if (!anchor.text.trim()) return
          dismissed.current = anchor
          editor.commands.setMeta("bubbleMenu", "hide")
          onSelectionRequest({ anchor, action: action as SelectionRequest["action"] })
        }}>{label}</Button>)}
    </BubbleMenu>
    <div role="group" aria-label="Text formatting" className="sticky top-0 z-10 flex flex-wrap gap-0.5 border-y bg-card px-3 py-1.5 sm:px-5">
      {controls.map(({ label, icon: Icon, active, disabled, run }) => <Button key={label} type="button" size="icon-sm"
        variant={active ? "secondary" : "ghost"} aria-label={label} aria-pressed={active} title={label} disabled={disabled}
        onMouseDown={(event) => event.preventDefault()} onClick={run}><Icon className="size-4" /></Button>)}
    </div>
    <EditorContent editor={editor} className="min-w-0 flex-1" />
    <Dialog open={insert !== null} onOpenChange={(open) => { if (!open) setInsert(null) }}>
      <DialogContent onCloseAutoFocus={(event) => { event.preventDefault(); editor.commands.focus() }}>
        <DialogHeader>
          <DialogTitle>{insert === "math" ? "Insert equation" : "Edit link"}</DialogTitle>
          <DialogDescription>{insert === "math" ? "Enter LaTeX for a displayed equation." : "Enter a URL, or clear it to remove the link."}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => { event.preventDefault(); apply() }}>
          <Input aria-label={insert === "math" ? "LaTeX equation" : "Link address"} value={value}
            maxLength={4000} onChange={(event) => setValue(event.target.value)} />
          {invalid && <p className="mt-2 text-sm text-destructive" role="alert">Enter a valid {insert === "math" ? "equation" : "link"}.</p>}
          <DialogFooter className="mt-4"><Button type="submit">{insert === "math" ? "Insert" : "Apply link"}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </>
})
