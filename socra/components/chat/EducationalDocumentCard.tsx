"use client"

import { useMemo, type ComponentProps } from "react"
import { Library, NotebookPen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { StudyMarkdown, type StudyMarkdownPresentation } from "@/components/notebook/NotebookReply"
import { educationalCitationLink, type EducationalDocument } from "@/lib/educational-document"

const generationUnavailable = new Set([
  "plan_transport_exhausted", "plan_retry_deadline", "generate_transport_exhausted", "generate_retry_deadline",
])

export function EducationalDocumentCard({ document, disabled, notebookCapture, onSaveToLibrary }: {
  document: EducationalDocument
  disabled?: boolean
  notebookCapture?: Pick<ComponentProps<"button">, "onClick" | "onPointerDown">
  onSaveToLibrary?: () => void
}) {
  const french = document.intent.language === "French"
  const rendering = useMemo<StudyMarkdownPresentation>(() => {
    const references = new Map(document.citations.map((ref) => [ref.citation_id, {
      label: "p. " + ref.span.page, title: document.source.filename + " · " + ref.span.page,
      href: educationalCitationLink(document, ref),
    }]))
    return { french, documentStyle: true, selectCopyFallback: true, citation: (id) => references.get(id) }
  }, [document, french])

  const findings = Array.isArray(document.verification?.findings) ? document.verification.findings : []
  const unavailable = findings.some((finding) => generationUnavailable.has(finding))
  const reviewUnavailable = findings.includes("review_provider_unavailable") || findings.includes("repair_provider_unavailable")
  let status = null
  if (document.historical_source) status = french ? "Source archivée" : "Archived source"
  else if (document.state === "review_pending" || document.state === "partial" && reviewUnavailable) {
    status = reviewUnavailable
      ? french ? "Vérification temporairement indisponible. Document incomplet." : "Review temporarily unavailable. Incomplete document."
      : french ? "Vérification du document en attente" : "Awaiting review"
  } else if (document.state === "draft" || document.state === "partial") {
    status = disabled ? french ? "Rédaction en cours…" : "Writing the document…"
      : unavailable ? french ? "Génération temporairement indisponible. Document incomplet." : "Generation temporarily unavailable. Incomplete document."
      : french ? "Document incomplet" : "Incomplete document"
  }
  return <article aria-label={document.title} className="mx-auto w-full min-w-0 max-w-[49rem] px-4 py-7 sm:px-8 sm:py-10"
    data-document-id={document.document_id} data-document-revision={document.revision_id}>
    {status && <p role="status" className="mb-5 text-sm text-muted-foreground">{status}</p>}
    <StudyMarkdown content={document.document_markdown} presentation={rendering} />
    {!disabled && document.remaining.length > 0 && <details className="mt-6 text-sm text-muted-foreground">
      <summary className="cursor-pointer font-medium">{french ? "Sections restantes" : "Remaining sections"}</summary>
      <ul className="mt-2 list-disc space-y-1 ps-5">{document.remaining.map((title, index) => <li key={index}>{title}</li>)}</ul>
    </details>}
    {(notebookCapture || onSaveToLibrary) && <div className="mt-8 flex flex-wrap items-center gap-2 border-t pt-4 print:hidden">
      {notebookCapture && <Button type="button" variant="outline" size="sm" {...notebookCapture}><NotebookPen />
        {french ? "Enregistrer dans le carnet" : "Save to Notebook"}</Button>}
      {onSaveToLibrary && <Button type="button" variant="ghost" size="sm" onClick={onSaveToLibrary}><Library />
        {french ? "Ajouter à la bibliothèque" : "Save to Library"}</Button>}
    </div>}
  </article>
}
