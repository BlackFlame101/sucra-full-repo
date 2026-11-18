import katex from "katex"
import type { JSONContent } from "@tiptap/react"
import { pdfPageUrl } from "@/lib/documents/pdf-page"
import { safeNoteLink, noteText, type NoteDocument } from "./document"

function escape(value: unknown) {
  return String(value ?? "").replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!)
}

const styles = [
  "@page { size: A4; margin: 16mm 17mm 19mm; @bottom-center { content: counter(page) ' / ' counter(pages); color: #526170; font: 9pt system-ui; } }",
  "*{box-sizing:border-box} body{margin:0;color:#141d28;background:#fff;font:11pt/1.55 system-ui,sans-serif}",
  "main{max-width:176mm;margin:auto} h1,h2,h3,h4,h5,h6{font-family:Georgia,serif;line-height:1.2;break-after:avoid;overflow-wrap:anywhere}",
  "h1{font-size:23pt;margin:0 0 6mm} h2{font-size:17pt;margin:8mm 0 3mm} h3,h4,h5,h6{font-size:13pt;margin:6mm 0 3mm}",
  "p,li{orphans:3;widows:3} p{margin:0 0 3.5mm} li p{margin-bottom:1.5mm} ul,ol{padding-left:6mm}",
  "a{color:#255c72;text-decoration:underline;overflow-wrap:anywhere} a.citation{font-size:.8em;white-space:nowrap}",
  "nav{margin:0 0 8mm;border-bottom:1px solid #cbd5df;padding-bottom:4mm} nav h2{margin-top:0} nav ul{list-style:none;padding:0}",
  "nav li{margin:1mm 0} nav .sub{padding-left:4mm} nav a{text-decoration:none}",
  "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;border:1px solid #cbd5df;padding:3mm;font:9pt/1.45 ui-monospace,monospace;break-inside:avoid}",
  "pre.long-cell{break-inside:auto;orphans:4;widows:4}",
  "code{font-family:ui-monospace,monospace} blockquote{margin:4mm 0;padding:2mm 0 1mm 4mm;border-left:2px solid #5c8295;break-inside:avoid}",
  "table{width:100%;border-collapse:collapse;table-layout:fixed;margin:4mm 0} td,th{padding:2mm;border:1px solid #cbd5df;vertical-align:top;overflow-wrap:anywhere}",
  "th{background:#eff3f6;text-align:left} td p,th p{margin:0} thead{display:table-header-group} tr{break-inside:avoid}",
  "math{max-width:100%;font-size:1.02em} .equation{text-align:center;margin:4mm 0;break-inside:avoid;overflow-wrap:anywhere}",
  ".controls{margin:0 0 8mm;padding-bottom:3mm;text-align:right} button{font:inherit;padding:1mm 3mm}",
  "@media screen{body{padding:6mm 4mm}} @media print{.controls{display:none} main{max-width:none}}",
].join("\n")

export function notebookPrintHtml(title: string, doc: NoteDocument, { french = false, nonce }: { french?: boolean; nonce?: string } = {}) {
  const entries: Array<{ id: string; level: number; label: string }> = []
  function render(node: JSONContent): string {
    const children = () => (node.content ?? []).map(render).join("")
    switch (node.type) {
      case "sourceBlock": return ""
      case "sourceCitation": {
        const attrs = node.attrs
        if (!attrs || !Number.isSafeInteger(attrs.page) || typeof attrs.documentId !== "string") return ""
        const href = pdfPageUrl(attrs.documentId, attrs.page, attrs.sourceHash)
        return '<a class="citation" href="' + escape(href) + '">p. ' + escape(attrs.page) + '</a>'
      }
      case "text": {
        return (node.marks ?? []).reduce((html, mark) => {
          const tag = { bold: "strong", italic: "em", strike: "s", code: "code" }[mark.type]
          if (tag) return "<" + tag + ">" + html + "</" + tag + ">"
          const url = mark.attrs?.href
          return mark.type === "link" && typeof url === "string" && safeNoteLink(url)
            ? '<a href="' + escape(url) + '">' + html + '</a>' : html
        }, escape(node.text))
      }
      case "heading": {
        const level = Math.min(6, Math.max(1, Number(node.attrs?.level) || 1))
        const id = "section-" + (entries.length + 1)
        entries.push({ id, level, label: noteText(node) })
        return "<h" + level + ' id="' + id + '">' + children() + "</h" + level + ">"
      }
      case "codeBlock": {
        const code = noteText(node)
        return (code.split("\n").length > 18 ? '<pre class="long-cell">' : "<pre>") +
          "<code>" + escape(code) + "</code></pre>"
      }
      case "inlineMath": case "blockMath": {
        const displayMode = node.type === "blockMath"
        const math = katex.renderToString(String(node.attrs?.latex ?? ""), {
          displayMode, output: "mathml", throwOnError: false, trust: false,
        })
        return displayMode ? '<div class="equation">' + math + '</div>' : math
      }
      case "table": {
        const [first, ...rest] = node.content ?? []
        if (first?.content?.every((cell) => cell.type === "tableHeader")) {
          return "<table><thead>" + render(first) + "</thead><tbody>" + rest.map(render).join("") + "</tbody></table>"
        }
        return "<table><tbody>" + children() + "</tbody></table>"
      }
      case "hardBreak": return "<br>"
      case "horizontalRule": return "<hr>"
      case "orderedList": return '<ol start="' + escape(Number(node.attrs?.start) || 1) + '">' + children() + "</ol>"
      case "taskItem": return "<li>" + (node.attrs?.checked ? "☑ " : "☐ ") + children() + "</li>"
      default: {
        const tag = { paragraph: "p", blockquote: "blockquote", bulletList: "ul", taskList: "ul", listItem: "li",
          tableRow: "tr", tableHeader: "th", tableCell: "td" }[node.type ?? ""]
        return tag ? "<" + tag + ">" + children() + "</" + tag + ">" : children()
      }
    }
  }
  const rendered = [...doc.content]
  const primaryTitle = rendered[0]?.type === "heading" && rendered[0].attrs?.level === 1 ? rendered.shift() : undefined
  const body = rendered.map(render).join("\n")
  const contents = entries.length > 1 ? "<nav><h2>" + (french ? "Sommaire" : "Contents") + "</h2><ul>" +
    entries.map(({ id, label, level }) => '<li' + (level > 2 ? ' class="sub"' : '') + '><a href="#' + id + '">' +
      escape(label) + "</a></li>").join("") + "</ul></nav>" : ""
  const displayTitle = primaryTitle ? noteText(primaryTitle) : title
  const controls = nonce ? '<div class="controls"><button id="print" type="button">' +
    (french ? "Imprimer ou enregistrer en PDF" : "Print or save as PDF") + '</button></div>' : ""
  const script = nonce ? '<script nonce="' + escape(nonce) +
    '">document.querySelector("#print").addEventListener("click", () => window.print());</script>' : ""
  return '<!doctype html><html lang="' + (french ? "fr" : "en") + '"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1"><title>' + escape(displayTitle) +
    "</title><style>" + styles + "</style></head><body><main>" + controls +
    "<h1>" + escape(displayTitle) + "</h1>" + contents + body + "</main>" + script + "</body></html>"
}
