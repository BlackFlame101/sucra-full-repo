import { pdfPageUrl } from "@/lib/documents/pdf-page"

export type EducationalCitation = {
  citation_id: string
  span: { page: number; start: number; end: number }
  quote: string
  checksum: string
}

export type EducationalDocument = {
  schema_version: 3
  format: "educational_document"
  document_id: string
  revision_id: string
  parent_revision_id: string | null
  state: "draft" | "partial" | "review_pending" | "approved" | "superseded"
  title: string
  summary: string
  document_markdown: string
  source: { document_id: string; filename: string; source_hash: string; index_generation: number }
  intent: { action: string; language: string; audience: string; depth: string; scope: string; document_type: string }
  sections: { section_id: string; title: string; parent_id: string | null; markdown_start: number; markdown_end: number }[]
  citations: EducationalCitation[]
  code_cells: { cell_id: string; section_id: string; language: string; checksum: string; origin: "source" | "generated" }[]
  remaining: string[]
  prerequisites: { section_id: string; title: string; page: number }[]
  verification?: { findings?: string[] }
  historical_source?: boolean
}

export const documentNodeId = /^[a-f0-9]{24}$/
export const sourceChecksum = /^[a-f0-9]{64}$/

export function isEducationalDocument(value: unknown): value is EducationalDocument {
  if (!value || typeof value !== "object") return false
  const doc = value as Partial<EducationalDocument>
  return doc.schema_version === 3 && doc.format === "educational_document" &&
    typeof doc.title === "string" && typeof doc.document_markdown === "string" &&
    typeof doc.document_id === "string" && documentNodeId.test(doc.document_id) &&
    typeof doc.revision_id === "string" && documentNodeId.test(doc.revision_id) &&
    Array.isArray(doc.sections) && Array.isArray(doc.citations) && Array.isArray(doc.code_cells) &&
    Array.isArray(doc.prerequisites) && Array.isArray(doc.remaining) &&
    typeof doc.intent?.language === "string" && typeof doc.source?.document_id === "string"
}

export function educationalCitationLink(doc: EducationalDocument, ref: EducationalCitation) {
  return doc.historical_source ? undefined : pdfPageUrl(doc.source.document_id, ref.span.page, doc.source.source_hash)
}

export function educationalCitations(doc: EducationalDocument) {
  return doc.citations.map((ref) => ({ document_id: doc.source.document_id, filename: doc.source.filename,
    page_number: ref.span.page, excerpt: ref.quote }))
}
