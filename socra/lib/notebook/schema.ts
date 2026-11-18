import { Extension, Node, getSchema } from "@tiptap/core"
import StarterKit from "@tiptap/starter-kit"
import TaskList from "@tiptap/extension-task-list"
import TaskItem from "@tiptap/extension-task-item"
import Mathematics from "@tiptap/extension-mathematics"
import { safeNoteLink, type NoteDocument } from "./document"
import { documentNodeId, sourceChecksum } from "@/lib/educational-document"
import { pdfPageUrl } from "@/lib/documents/pdf-page"

export const notebookId = /^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i

const SourceBlock = Node.create({
  name: "sourceBlock",
  group: "block",
  atom: true,
  addAttributes: () => ({ sourceId: { default: null } }),
  renderHTML: ({ node }) => {
    const id = node.attrs.sourceId
    return ["aside", { class: "notebook-source", contenteditable: "false" },
      typeof id === "string" && notebookId.test(id)
        ? ["a", { href: `/api/notebook/source/${id}`, target: "_blank", rel: "noopener noreferrer" }, "Open original Socra response"]
        : "Socra source unavailable"]
  },
})

const SourceCitation = Node.create({
  name: "sourceCitation", group: "inline", inline: true, atom: true,
  addAttributes: () => Object.fromEntries(
    ["citationId", "documentId", "sourceHash", "page", "start", "end", "checksum"].map((key) => [key, { default: null }])
  ),
  renderHTML: ({ node }) => {
    const { documentId, page, sourceHash } = node.attrs
    return ["a", { href: pdfPageUrl(documentId, page, sourceHash), target: "_blank", rel: "noopener noreferrer",
      class: "notebook-inline-citation", contenteditable: "false" }, "p. " + page]
  },
})

const EducationalIdentity = Extension.create({
  name: "educationalIdentity",
  addGlobalAttributes: () => [
    { types: ["heading"], attributes: { sectionId: { default: null } } },
    { types: ["codeBlock"], attributes: { cellId: { default: null } } },
  ],
})

const Table = Node.create({
  name: "table", group: "block", content: "tableRow+", isolating: true,
  parseHTML: () => [{ tag: "table" }],
  renderHTML: () => ["table", ["tbody", 0]],
})

const TableRow = Node.create({
  name: "tableRow", content: "(tableHeader|tableCell)+",
  parseHTML: () => [{ tag: "tr" }], renderHTML: () => ["tr", 0],
})

const TableCell = Node.create({
  name: "tableCell", content: "block+", isolating: true,
  parseHTML: () => [{ tag: "td" }], renderHTML: () => ["td", 0],
})

const TableHeader = Node.create({
  name: "tableHeader", content: "block+", isolating: true,
  parseHTML: () => [{ tag: "th" }], renderHTML: () => ["th", { scope: "col" }, 0],
})

export const notebookExtensions = [
  StarterKit.configure({ heading: { levels: [1, 2, 3, 4, 5, 6] }, link: {
    openOnClick: false, isAllowedUri: (href) => safeNoteLink(href),
  } }),
  TaskList,
  TaskItem.configure({ nested: true }),
  Mathematics.configure({ katexOptions: { throwOnError: false, trust: false } }),
  SourceBlock,
  SourceCitation,
  EducationalIdentity,
  Table, TableRow, TableCell, TableHeader,
]

const schema = getSchema(notebookExtensions)
export function validateNoteDocument(value: unknown): NoteDocument {
  if (!value || typeof value !== "object" || new TextEncoder().encode(JSON.stringify(value)).length > 1_000_000) {
    throw new Error("The note is too large or invalid.")
  }
  function checkDepth(node: unknown, depth: number) {
    if (!node || typeof node !== "object" || depth > 30) throw new Error("The note contains invalid or deeply nested content.")
    if ("content" in node) {
      if (!Array.isArray(node.content)) throw new Error("The note contains invalid content.")
      for (const child of node.content) checkDepth(child, depth + 1)
    }
  }
  checkDepth(value, 0)
  const doc = schema.nodeFromJSON(value)
  if (doc.type !== schema.topNodeType) throw new Error("The note must be a document.")
  doc.check()
  doc.descendants((node) => {
    if (node.type.name === "sourceBlock" && !notebookId.test(node.attrs.sourceId ?? "")) throw new Error("Invalid Socra source.")
    if (node.type.name === "sourceCitation") {
      const { citationId, documentId, sourceHash, page, start, end, checksum } = node.attrs
      if (!documentNodeId.test(citationId) || !notebookId.test(documentId) || !sourceChecksum.test(sourceHash) ||
          !sourceChecksum.test(checksum) || !Number.isSafeInteger(page) || page < 1 ||
          !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end <= start) {
        throw new Error("Invalid PDF citation.")
      }
    }
    for (const id of [node.attrs.sectionId, node.attrs.cellId]) {
      if (id != null && !documentNodeId.test(id)) throw new Error("Invalid educational content identity.")
    }
    if (["inlineMath", "blockMath"].includes(node.type.name) &&
        (typeof node.attrs.latex !== "string" || node.attrs.latex.length > 4_000)) throw new Error("Invalid equation.")
    for (const mark of node.marks) {
      if (mark.type.name === "link" && (typeof mark.attrs.href !== "string" || !safeNoteLink(mark.attrs.href))) {
        throw new Error("Use a valid HTTPS, HTTP, email or Socra link.")
      }
    }
  })
  const result = doc.toJSON() as NoteDocument
  // Use editor-owned link attributes even if a direct request supplies extras.
  function clean(node: NoteDocument["content"][number]) {
    for (const mark of node.marks ?? []) if (mark.type === "link") {
      mark.attrs = { href: mark.attrs?.href, target: "_blank", rel: "noopener noreferrer" }
    }
    for (const child of node.content ?? []) clean(child)
  }
  clean(result)
  return result
}
