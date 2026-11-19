import { Marked, type Token, type Tokens } from "marked"
import type { JSONContent } from "@tiptap/react"

export type NoteDocument = JSONContent & { type: "doc"; content: JSONContent[] }
export const emptyNote: NoteDocument = { type: "doc", content: [{ type: "paragraph" }] }

export function safeNoteLink(href: string) {
  return /^(https?:\/\/|mailto:|\/(?![\/\\]))/i.test(href) && !/[\s\\\u0000-\u001f]/.test(href)
}

type MathToken = Tokens.Generic & { latex: string }
const markdown = new Marked({
  extensions: [{
    name: "blockMath", level: "block",
    tokenizer(src) {
      const match = /^(?:\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]) *(?:\n|$)/.exec(src)
      if (match) return { type: "blockMath", raw: match[0], latex: (match[1] ?? match[2]).trim() }
    },
  }, {
    name: "inlineMath", level: "inline",
    start: (src) => { const at = src.search(/\$|\\\(/); return at < 0 ? undefined : at },
    tokenizer(src) {
      const match = /^(?:\$(?!\$)([^$\n]+?)\$(?!\$)|\\\((.+?)\\\))/.exec(src)
      const latex = (match?.[1] ?? match?.[2])?.trim()
      if (match && latex) return { type: "inlineMath", raw: match[0], latex }
    },
  }],
})

const textNode = (text: string, marks: JSONContent["marks"] = []): JSONContent[] =>
  text ? [{ type: "text", text, ...(marks.length ? { marks } : {}) }] : []

function inline(tokens: Token[], marks: NonNullable<JSONContent["marks"]> = []): JSONContent[] {
  return tokens.flatMap((token) => {
    const t = token as Tokens.Generic
    switch (t.type) {
      case "inlineMath": return [{ type: t.type, attrs: { latex: (t as MathToken).latex } }]
      case "strong": case "em": case "del":
        return inline(t.tokens ?? [], [...marks, { type: { strong: "bold", em: "italic", del: "strike" }[t.type] }])
      case "codespan": return textNode(t.text, [{ type: "code" }])
      case "link": return inline(t.tokens ?? [], safeNoteLink(t.href) ? [...marks, { type: "link", attrs: { href: t.href } }] : marks)
      case "br": return [{ type: "hardBreak" }]
      case "text": return t.tokens?.length ? inline(t.tokens, marks) : textNode(t.text, marks)
      case "escape": case "image": return textNode(t.text, marks)
      default: return textNode(t.raw, marks)
    }
  })
}

function blocks(tokens: Token[]): JSONContent[] {
  return tokens.flatMap((token) => {
    const t = token as Tokens.Generic
    switch (t.type) {
      case "space": return []
      case "heading": return [{ type: "heading", attrs: { level: Math.min(t.depth, 3) }, content: inline(t.tokens ?? []) }]
      case "code": return [{ type: "codeBlock", attrs: { language: t.lang?.split(/\s/)[0] || null }, content: textNode(t.text) }]
      case "hr": return [{ type: "horizontalRule" }]
      case "blockMath": return [{ type: t.type, attrs: { latex: (t as MathToken).latex } }]
      case "blockquote": return [{ type: "blockquote", content: blocks(t.tokens ?? []) }]
      case "table": {
        const { header, rows } = token as Tokens.Table
        return [{ type: "table", content: [header, ...rows].map((row, index) => ({
          type: "tableRow",
          content: row.map((cell) => ({
            type: index === 0 ? "tableHeader" : "tableCell",
            content: [{ type: "paragraph", content: inline(cell.tokens) }],
          })),
        })) }]
      }
      case "list": {
        const items = t.items as Tokens.ListItem[]
        const tasks = items.every((item) => item.task)
        return [{ type: tasks ? "taskList" : t.ordered ? "orderedList" : "bulletList",
          ...(t.ordered && !tasks ? { attrs: { start: t.start } } : {}),
          content: items.map((item) => {
            const children = blocks(item.tokens)
            if (children[0]?.type !== "paragraph") children.unshift({ type: "paragraph" })
            return { type: tasks ? "taskItem" : "listItem", ...(tasks ? { attrs: { checked: item.checked } } : {}), content: children }
          }) }]
      }
      case "paragraph": case "text":
        return [{ type: "paragraph", content: t.tokens?.length ? inline(t.tokens) : textNode(t.text) }]
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

export function suggestionNote(value: string): NoteDocument {
  const wrapped = /^(`{3,}|~{3,})(?:markdown|md)[ \t]*\r?\n([\s\S]*?)\r?\n\1[ \t]*$/i.exec(value.trim())
  return markdownNote(wrapped?.[2] ?? value)
}

export function fencedMarkdownPaste(value: string): NoteDocument | null {
  if (!/^[ \t]*(?:`{3,}|~{3,})[^\r\n]*\r?$/m.test(value)) return null
  const tokens = lexStudyMarkdown(value)
  // Fenced blocks may be inside a numbered list, as with Socra's command examples.
  const hasFence = (items: Token[]): boolean => items.some((item) => {
    const token = item as Tokens.Generic
    if (token.type === "code") return /^ {0,3}(?:`{3,}|~{3,})/.test(token.raw)
    if (token.type === "list") return (token.items as Tokens.ListItem[]).some((entry) => hasFence(entry.tokens))
    return token.type === "blockquote" && hasFence(token.tokens ?? [])
  })
  return hasFence(tokens) ? { type: "doc", content: blocks(tokens) } : null
}

export function noteText(node: JSONContent): string {
  if (node.type === "sourceBlock") return ""
  if (node.type === "hardBreak") return "\n"
  if (node.type === "inlineMath" || node.type === "blockMath") return node.attrs?.latex ?? ""
  if (node.text) return node.text
  const separator = node.type === "tableRow" ? "\t" :
    ["paragraph", "heading", "codeBlock"].includes(node.type ?? "") ? "" : "\n"
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
