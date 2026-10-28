"use client"

import { KeyTerms } from "./KeyTerms"
import { SuggestedReading } from "./SuggestedReading"

interface Reading {
  documentName: string
  pageNumber: number
  section: string
  chapter?: string
}

export interface CourseContextMaterial {
  documentId: string
  filename: string
  status: string | null
  summary: { title: string; summary: string; page_start: number; page_end: number } | null
  sections: Array<{ title: string; summary: string; pageStart: number; pageEnd: number }>
}

interface ContextPanelProps {
  keyTerms: string[]
  suggestedReadings: Reading[]
  courseMaterials: CourseContextMaterial[]
  isLoading?: boolean
}

export function ContextPanel({
  keyTerms,
  suggestedReadings,
  courseMaterials,
  isLoading,
}: ContextPanelProps) {
  return (
    <div className="flex h-full w-full min-w-0 flex-col overflow-hidden border-l border-border/40 bg-card/20">
      {/* Header */}
      <div className="border-b border-border/40 px-4 py-3 shrink-0">
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          Course Context
        </h2>
      </div>

      {/* Content */}
      <div className="min-h-0 w-full min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain">
        <div className="box-border w-full min-w-0 space-y-5 p-3 sm:p-4">
          <section className="w-full min-w-0 overflow-hidden">
            <h3 className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Course Map
            </h3>
            {courseMaterials.length === 0 ? (
              <p className="text-xs text-muted-foreground/70">Upload course PDFs to see their summaries and section map here.</p>
            ) : (
              <div className="w-full min-w-0 space-y-3">
                {courseMaterials.map((material) => (
                  <article key={material.documentId} className="box-border w-full min-w-0 overflow-hidden rounded-xl border border-border/50 bg-card/50 p-3">
                    <h4 className="max-w-full truncate text-xs font-semibold" title={material.filename}>{material.filename}</h4>
                    {material.summary ? (
                      <>
                        <p className="mt-2 line-clamp-4 break-words [overflow-wrap:anywhere] text-xs leading-relaxed text-muted-foreground">{material.summary.summary}</p>
                        {(() => {
                          const summaryKey = `${material.summary?.title.trim().toLocaleLowerCase()}|${material.summary?.summary.trim().replace(/\s+/g, " ").toLocaleLowerCase()}`
                          const sections = material.sections.filter((section) =>
                            `${section.title.trim().toLocaleLowerCase()}|${section.summary.trim().replace(/\s+/g, " ").toLocaleLowerCase()}` !== summaryKey
                          )
                          return sections.length > 0 && (
                          <div className="mt-3 w-full min-w-0 space-y-3 border-t border-border/40 pt-3">
                            {sections.slice(0, 5).map((section, index) => (
                              <div key={`${material.documentId}-${index}`} className="w-full min-w-0 overflow-hidden">
                                <p className="line-clamp-2 break-words [overflow-wrap:anywhere] text-xs font-medium">{section.title}</p>
                                <p className="mt-0.5 line-clamp-3 break-words [overflow-wrap:anywhere] text-[11px] leading-relaxed text-muted-foreground">{section.summary}</p>
                                <p className="mt-1 text-[10px] text-muted-foreground/70">Pages {section.pageStart}–{section.pageEnd}</p>
                              </div>
                            ))}
                            {sections.length > 5 && (
                              <p className="text-[10px] text-muted-foreground">+{sections.length - 5} more sections</p>
                            )}
                          </div>
                          )
                        })()}
                      </>
                    ) : (
                      <p className="mt-2 text-xs text-muted-foreground">
                        {material.status === "processing" ? "Course map is being prepared…" : "No course map yet. Delete and reupload this PDF from the course page to rebuild its page index and summary."}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
          <KeyTerms terms={keyTerms} isLoading={isLoading} />
          <SuggestedReading readings={suggestedReadings} isLoading={isLoading} />
        </div>
      </div>
    </div>
  )
}
