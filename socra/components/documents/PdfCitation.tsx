import { pdfPageUrl } from "@/lib/documents/pdf-page"

export { pdfPageUrl }

export function PdfCitation({ documentId, page, filename }: { documentId?: string | null; page?: number | null; filename: string }) {
  const label = page ? `${filename} · page ${page}` : filename
  if (!documentId || !page || page < 1) return <span>{label}</span>
  return <a className="font-medium text-secondary underline-offset-4 hover:underline focus-visible:underline"
    href={pdfPageUrl(documentId, page)} target="_blank" rel="noopener noreferrer">{label}<span className="sr-only"> (opens PDF in a new tab)</span></a>
}
