import { Marked, type Token, type Tokens } from "marked"
import type { JSONContent } from "@tiptap/react"
import type { EducationalDocument } from "@/lib/educational-document"

export type NoteDocument = JSONContent & { type: "doc"; content: JSONContent[] }
export const emptyNote: NoteDocument = { type: "doc", content: [{ type: "paragraph" }] }

export function safeNoteLink(href: string) {
  return /^(https?:\/\/|mailto:|\/(?![\/\\]))/i.test(href) && !/[\s\\\u0000-\u001f]/.test(href)
}

type MathToken = Tokens.Generic & { latex: string }
const markdown = new Marked({
  extensions: [{
    name: "sourceCitation", level: "inline",
    start: (src) => { const at = src.indexOf("[["); return at < 0 ? undefined : at },
    tokenizer(src) {
      const match = /^\[\[([a-f0-9]{24})\]\]/.exec(src)
      if (match) return { type: "sourceCitation", raw: match[0], citationId: match[1] }
    },
  }, {
    name: "blockMath", level: "block",
    tokenizer(src) {
      const match = /^(?:\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]) *(?:\n|$)/.exec(src)
      if (match) return { type: "blockMath", raw: match[0], latex: (match[1] ?? match[2]).trim() }
    },
  }, {
    name: "inlineMath", level: "inline",
    start: (src) => { const at = src.search(/\$|\\\(/); return at < 0 ? undefined : at },
    tokenizer(src) {
      const match = /^(?:\$(?!\s|\$)([^$\n]+?)\$|\\\((.+?)\\\))/.exec(src)
      if (match) return { type: "inlineMath", raw: match[0], latex: (match[1] ?? match[2]).trim() }
    },
  }],
})

const textNode = (text: string, marks: JSONContent["marks"] = []): JSONContent[] =>
  text ? [{ type: "text", text, ...(marks.length ? { marks } : {}) }] : []

type NoteImport = { citations: ReadonlyMap<string, JSONContent>; headings: ReadonlyMap<Token, string> }

function inline(tokens: Token[], marks: NonNullable<JSONContent["marks"]> = [], input?: NoteImport): JSONContent[] {
  return tokens.flatMap((token) => {
    const t = token as Tokens.Generic
    switch (t.type) {
      case "sourceCitation": return input?.citations.has(t.citationId) ? [input.citations.get(t.citationId)!] : textNode(t.raw, marks)
      case "inlineMath": return [{ type: t.type, attrs: { latex: (t as MathToken).latex } }]
      case "strong": case "em": case "del":
        return inline(t.tokens ?? [], [...marks, { type: { strong: "bold", em: "italic", del: "strike" }[t.type] }], input)
      case "codespan": return textNode(t.text, [{ type: "code" }])
      case "link": return inline(t.tokens ?? [], safeNoteLink(t.href) ? [...marks, { type: "link", attrs: { href: t.href } }] : marks, input)
      case "br": return [{ type: "hardBreak" }]
      case "text": return t.tokens?.length ? inline(t.tokens, marks, input) : textNode(t.text, marks)
      case "escape": case "image": return textNode(t.text, marks)
      default: return textNode(t.raw, marks)
    }
  })
}

function blocks(tokens: Token[], input?: NoteImport): JSONContent[] {
  return tokens.flatMap((token) => {
    const t = token as Tokens.Generic
    switch (t.type) {
      case "space": return []
      case "heading": return [{ type: "heading", attrs: { level: Math.min(t.depth, input ? 6 : 3),
        ...(input?.headings.has(token) ? { sectionId: input.headings.get(token) } : {}) }, content: inline(t.tokens ?? [], [], input) }]
      case "code": {
        const [language, identity] = (t.lang ?? "").split(/\s+/, 2)
        const cellId = input && /^cell:[a-f0-9]{24}$/.test(identity ?? "") ? identity.slice(5) : null
        return [{ type: "codeBlock", attrs: { language: language || null, ...(cellId ? { cellId } : {}) }, content: textNode(t.text) }]
      }
      case "hr": return [{ type: "horizontalRule" }]
      case "blockMath": return [{ type: t.type, attrs: { latex: (t as MathToken).latex } }]
      case "blockquote": return [{ type: "blockquote", content: blocks(t.tokens ?? [], input) }]
      case "table": {
        if (input) {
          const table = token as Tokens.Table
          return [{ type: "table", content: [table.header, ...table.rows].map((row, index) => ({
            type: "tableRow", content: row.map((cell) => ({ type: index === 0 ? "tableHeader" : "tableCell",
              content: [{ type: "paragraph", content: inline(cell.tokens, [], input) }] })),
          })) }]
        }
        // Notebook has no editable table node. Keep the Markdown rows copyable
        // using the editor's existing hard breaks instead of collapsed whitespace.
        const rows = t.raw.replace(/\n+$/, "").split("\n")
        return [{ type: "paragraph", content: rows.flatMap((row: string, index: number) => [
          ...(index ? [{ type: "hardBreak" }] : []), ...textNode(row),
        ]) }]
      }
      case "list": {
        const items = t.items as Tokens.ListItem[]
        const tasks = items.every((item) => item.task)
        return [{ type: tasks ? "taskList" : t.ordered ? "orderedList" : "bulletList",
          ...(t.ordered && !tasks ? { attrs: { start: t.start } } : {}),
          content: items.map((item) => {
            const children = blocks(item.tokens, input)
            if (children[0]?.type !== "paragraph") children.unshift({ type: "paragraph" })
            return { type: tasks ? "taskItem" : "listItem", ...(tasks ? { attrs: { checked: item.checked } } : {}), content: children }
          }) }]
      }
      case "paragraph": case "text":
        return [{ type: "paragraph", content: t.tokens?.length ? inline(t.tokens, [], input) : textNode(t.text) }]
      default: return [{ type: "paragraph", content: textNode(t.raw) }]
    }
  })
}

export function lexStudyMarkdown(value: string): Token[] {
  return markdown.lexer(value)
}

export function markdownNote(value: string): NoteDocument {
  const content = blocks(lexStudyMarkdown(value))
  return content.length ? { type: "doc", content } : emptyNote
}

export function educationalNote(doc: EducationalDocument): NoteDocument {
  const citations = new Map(doc.citations.map((ref) => [ref.citation_id, { type: "sourceCitation", attrs: {
    citationId: ref.citation_id, documentId: doc.source.document_id, sourceHash: doc.source.source_hash,
    page: ref.span.page, start: ref.span.start, end: ref.span.end, checksum: ref.checksum,
  } }]))
  const markup = doc.document_markdown
  const tokens = lexStudyMarkdown(markup)
  const positions = new Map(doc.sections.map((section) => [section.markdown_start, section.section_id]))
  const headings = new Map<Token, string>()
  let cursor = 0
  for (const token of tokens) {
    const start = markup.indexOf(token.raw, cursor)
    if (start < 0) continue
    cursor = start + token.raw.length
    if (token.type === "heading") {
      const id = positions.get(Array.from(markup.slice(0, start)).length)
      if (id) headings.set(token, id)
    }
  }
  return { type: "doc", content: blocks(tokens, { citations, headings }) }
}

export function suggestionNote(value: string): NoteDocument {
  const wrapped = /^(`{3,}|~{3,})(?:markdown|md)[ \t]*\r?\n([\s\S]*?)\r?\n\1[ \t]*$/i.exec(value.trim())
  return markdownNote(wrapped?.[2] ?? value)
}

export function noteText(node: JSONContent): string {
  if (node.type === "sourceBlock") return ""
  if (node.type === "sourceCitation") return "p. " + node.attrs?.page
  if (node.type === "hardBreak") return "\n"
  if (node.type === "inlineMath" || node.type === "blockMath") return node.attrs?.latex ?? ""
  if (node.text) return node.text
  const separator = ["paragraph", "heading", "codeBlock"].includes(node.type ?? "") ? "" : "\n"
  return node.content?.map(noteText).join(separator) ?? ""
}

export function readNoteDocument(value: unknown, legacy: string, legacyMarkdown = false): NoteDocument {
  if (value && typeof value === "object" && "type" in value && value.type === "doc" &&
      "content" in value && Array.isArray(value.content) && value.content.length) return value as NoteDocument
  // Old imports sometimes lack source metadata. Recognize unmistakable
  // multiline Markdown while retaining ordinary plain text and all stored JSON.
  if (legacyMarkdown || /^(?: {0,3}(?:`{3,}|~{3,})).+\r?\n[\s\S]*^(?: {0,3}(?:`{3,}|~{3,}))[ \t]*$/m.test(legacy) ||
      /^(?: {0,3}#[#]{0,5}\s+.+\r?\n)[\s\S]*^ {0,3}(?:[*+-]|\d+[.)])\s+\S/m.test(legacy) ||
      /^ {0,3}([*+-]) +\S[^\r\n]*\r?\n {0,3}\1 +\S/m.test(legacy)) return markdownNote(legacy)
  return { type: "doc", content: legacy.split(/\r?\n/).map((line) => ({ type: "paragraph", content: textNode(line) })) }
}

const normalized = (value: string) => value.replace(/\s+/g, " ").trim()

// Only copy text that can be located in a persisted response. Restrict selections
// to one text block so links, marks and code can be sliced without guessing.
export function selectNoteText(document: NoteDocument, selection: string): JSONContent[] | null {
  const needle = normalized(selection)
  if (!needle) return null
  function find(node: JSONContent): JSONContent | undefined {
    if (["paragraph", "heading", "codeBlock"].includes(node.type ?? "")) {
      const value = noteText(node)
      const trimmed = value.trimStart()
      const offset = value.length - trimmed.length
      const parts = [...trimmed.matchAll(/\S|\s+/g)]
      const projected = parts.map((part) => part[0].trim() ? part[0] : " ").join("")
      const at = projected.indexOf(needle)
      if (at < 0) return
      const start = offset + parts[at].index
      const last = parts[at + needle.length - 1]
      const end = offset + last.index + last[0].length
      let position = 0
      const content = (node.content ?? []).flatMap((child) => {
        const text = noteText(child)
        const from = Math.max(0, start - position)
        const to = Math.min(text.length, end - position)
        position += text.length
        if (from >= to) return []
        if (child.type === "text") return [{ ...child, text: text.slice(from, to) }]
        return from === 0 && to === text.length ? [child] : []
      })
      if (normalized(content.map(noteText).join("")) === needle) return { ...node, content }
      return
    }
    for (const child of node.content ?? []) {
      const found = find(child)
      if (found) return found
    }
  }
  const found = find(document)
  return found ? [found] : null
}
