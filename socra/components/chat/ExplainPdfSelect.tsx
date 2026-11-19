"use client"

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { ExplainFormat } from "@/lib/socra-ws"

type ExplainPdf = { id: string; filename: string }

export function ExplainFormatSelect({ value, onChange }: {
  value?: ExplainFormat; onChange: (format?: ExplainFormat) => void
}) {
  return <Select value={value ?? "auto"}
    onValueChange={(format) => onChange(format === "focused" || format === "full_document" ? format : undefined)}>
    <SelectTrigger className="w-40 max-w-full" aria-label="Explanation format"><SelectValue /></SelectTrigger>
    <SelectContent>
      <SelectItem value="auto">Automatic depth</SelectItem>
      <SelectItem value="focused">Focused explanation</SelectItem>
      <SelectItem value="full_document">Full PDF report</SelectItem>
    </SelectContent>
  </Select>
}

export function ExplainPdfSelect({ documents, value, onChange }: {
  documents: ExplainPdf[]; value: string; onChange: (id: string) => void
}) {
  if (!documents.length) return null
  return (
    <Select value={value || "automatic"} onValueChange={(id) => onChange(id === "automatic" ? "" : id)}>
      <SelectTrigger className="w-44 max-w-full" aria-label="PDF source"><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value="automatic">Automatic PDF source</SelectItem>
        {documents.map((pdf) => <SelectItem key={pdf.id} value={pdf.id}>{pdf.filename}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}
