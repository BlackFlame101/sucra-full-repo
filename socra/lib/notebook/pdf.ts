import { readFileSync } from "node:fs"
import { join } from "node:path"
import type { JSONContent } from "@tiptap/react"
import PDFDocument from "pdfkit"
import { noteText, safeNoteLink, type NoteDocument } from "./document"

const fontFiles = {
  "Note": "@fontsource/noto-sans/files/noto-sans-latin-400-normal.woff",
  "Note Bold": "@fontsource/noto-sans/files/noto-sans-latin-700-normal.woff",
  "Note Italic": "@fontsource/noto-sans/files/noto-sans-latin-400-italic.woff",
  "Note Bold Italic": "@fontsource/noto-sans/files/noto-sans-latin-700-italic.woff",
  "Note Symbols": "@fontsource/noto-sans-symbols-2/files/noto-sans-symbols-2-symbols-400-normal.woff",
}
let fonts: [string, Buffer][] | undefined

type Run = { text: string; font: string; link?: string }
type Layout = { indent: number; size: number; gap: number; prefix?: string }

function inlineLines(content: JSONContent[], origin: string, bold: boolean): Run[][] {
  const lines: Run[][] = [[]]
  for (const node of content) {
    if (node.type === "hardBreak") {
      lines.push([])
      continue
    }
    const text = noteText(node)
    const marks = node.marks ?? []
    const hasBold = bold || marks.some((mark) => mark.type === "bold")
    const italic = marks.some((mark) => mark.type === "italic")
    const font = marks.some((mark) => mark.type === "code") ? "Courier"
      : `Note${hasBold ? " Bold" : ""}${italic ? " Italic" : ""}`
    const href = marks.find((mark) => mark.type === "link")?.attrs?.href
    const link = typeof href === "string" && safeNoteLink(href)
      ? href.startsWith("/") ? new URL(href, origin).href : href : undefined
    for (const part of text.split(/([✓✗☑☐])/u).filter(Boolean)) {
      lines.at(-1)!.push({ text: part, font: /^[✓✗☑☐]$/u.test(part) ? "Note Symbols" : font, link })
    }
  }
  return lines
}

export async function notebookPdf(title: string, note: NoteDocument, origin: string): Promise<Buffer> {
  fonts ??= Object.entries(fontFiles).map(([name, file]) => [name, readFileSync(join(process.cwd(), "node_modules", file))])
  const doc = new PDFDocument({ size: "A4", margin: 46, bufferPages: true, info: { Title: title } })
  for (const [name, bytes] of fonts) doc.registerFont(name, bytes)
  const chunks: Buffer[] = []
  const output = new Promise<Buffer>((resolve, reject) => {
    doc.on("data", (chunk: Buffer) => chunks.push(chunk))
    doc.once("end", () => resolve(Buffer.concat(chunks)))
    doc.once("error", reject)
  })

  function flow(lines: Run[][], { indent, size, gap, prefix }: Layout) {
    const x = doc.page.margins.left + indent
    const width = Math.max(48, doc.page.width - doc.page.margins.right - x)
    if (prefix) lines[0].unshift({ text: prefix, font: /^[☑☐]/u.test(prefix) ? "Note Symbols" : "Note" })
    for (const line of lines) {
      doc.fontSize(size)
      if (!line.length) {
        doc.font("Note").moveDown(0.5)
        continue
      }
      for (const [index, run] of line.entries()) {
        doc.font(run.font).fillColor(run.link ? "#245873" : "#17212b")
        const options = { width, lineGap: 2, continued: index < line.length - 1, link: run.link ?? null }
        if (index === 0) doc.text(run.text, x, doc.y, options)
        else doc.text(run.text, options)
      }
    }
    doc.y += gap
  }

  function render(node: JSONContent, level = 0, prefix?: string): void {
    const indent = Math.min(level, 20) * 12
    const children = node.content ?? []
    switch (node.type) {
      case "sourceBlock": return
      case "heading": {
        const depth = Number(node.attrs?.level)
        const size = depth === 1 ? 21 : depth === 2 ? 15 : 12
        if (doc.y + 54 > doc.page.height - doc.page.margins.bottom) doc.addPage()
        if (depth !== 1) doc.y += 5
        flow(inlineLines(children, origin, true), { indent, size, gap: 6 })
        return
      }
      case "paragraph":
        flow(inlineLines(children, origin, false), { indent, size: 10.5, gap: 5, prefix })
        return
      case "bulletList": case "taskList": case "orderedList":
        for (const [index, item] of children.entries()) {
          const marker = node.type === "orderedList" ? `${(Number(node.attrs?.start) || 1) + index}. `
            : node.type === "taskList" ? item.attrs?.checked ? "☑ " : "☐ " : "• "
          item.content?.forEach((child, position) => render(child, level + 1, position === 0 ? marker : undefined))
        }
        return
      case "blockquote":
        children.forEach((child) => render(child, level + 1))
        return
      case "horizontalRule": {
        const x = doc.page.margins.left + indent
        doc.save().strokeColor("#d4dde4").moveTo(x, doc.y).lineTo(doc.page.width - doc.page.margins.right, doc.y).stroke().restore()
        doc.y += 8
        return
      }
      case "codeBlock": case "blockMath":
        flow(noteText(node).split("\n").map((text) => text ? [{ text, font: node.type === "codeBlock" ? "Courier" : "Note" }] : []),
          { indent, size: 10, gap: 6 })
        return
      default:
        children.forEach((child) => render(child, level))
    }
  }

  const first = note.content.find((node) => node.type !== "sourceBlock")
  if (first?.type !== "heading" || first.attrs?.level !== 1) {
    flow([[{ text: title, font: "Note Bold" }]], { indent: 0, size: 21, gap: 6 })
  }
  note.content.forEach((node) => render(node))
  const pages = doc.bufferedPageRange()
  for (let index = 0; index < pages.count; index++) {
    doc.switchToPage(pages.start + index)
    const label = `${index + 1} / ${pages.count}`
    doc.font("Note").fontSize(9).fillColor("#536373")
    doc.text(label, (doc.page.width - doc.widthOfString(label)) / 2, doc.page.height - 30, { lineBreak: false })
  }
  doc.end()
  return output
}
