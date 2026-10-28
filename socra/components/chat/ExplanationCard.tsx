"use client"

import { ArrowRight, BookOpen, Lightbulb } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { PublicExplanation } from "@/lib/socra-ws"

export function ExplanationCard({ explanation, onDiscuss, disabled = false }: {
  explanation: PublicExplanation
  onDiscuss: (question: string) => void
  disabled?: boolean
}) {
  return (
    <section className="mx-4 mb-4 space-y-5 rounded-2xl border border-primary/20 bg-card p-5 shadow-sm sm:mx-6 sm:p-6" aria-live="polite">
      <div className="flex items-center gap-2 text-primary">
        <BookOpen className="h-5 w-5" />
        <h3 className="text-lg font-semibold text-foreground">Course explanation</h3>
      </div>
      <div className="space-y-2"><h4 className="text-sm font-semibold">Definition</h4><p className="text-sm leading-relaxed text-muted-foreground">{explanation.definition}</p></div>
      <div className="space-y-2"><h4 className="text-sm font-semibold">Intuition</h4><p className="text-sm leading-relaxed text-muted-foreground">{explanation.intuition}</p></div>
      {explanation.sections?.length ? <div className="space-y-4">{explanation.sections.map((section, index) => <section key={`${section.heading}-${index}`} className="space-y-2 rounded-xl border border-border/60 p-4"><h4 className="font-semibold text-foreground">{section.heading}</h4><p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{section.content}</p></section>)}</div> : null}
      <div className="space-y-2"><h4 className="text-sm font-semibold">From your course</h4><p className="text-sm leading-relaxed text-muted-foreground">{explanation.course_example}</p></div>
      <div className="rounded-xl bg-muted/40 p-4"><h4 className="flex items-center gap-2 text-sm font-semibold"><Lightbulb className="h-4 w-4 text-primary" />Common pitfalls</h4><ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-muted-foreground">{explanation.common_pitfalls.map((item, index) => <li key={index}>{item}</li>)}</ul></div>
      <details className="rounded-xl border border-border/70 px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium">Course sources ({explanation.citations.length})</summary>
        <ul className="mt-3 space-y-3 text-sm">{explanation.citations.map((citation, index) => <li key={`${citation.document_id}-${citation.page_number}-${index}`}><p className="font-medium">{citation.filename} · page {citation.page_number ?? "page unavailable"}</p><p className="mt-1 text-muted-foreground">{citation.excerpt ? `“${citation.excerpt}”` : "The source page is cited, but the excerpt is unavailable."}</p></li>)}</ul>
      </details>
      <div className="rounded-xl border border-primary/15 bg-primary/5 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Check your understanding</p>
        <p className="mt-2 text-sm font-medium leading-relaxed">{explanation.check_question}</p>
        <Button className="mt-4 gap-2" onClick={() => onDiscuss(explanation.check_question)} disabled={disabled}>Discuss this question in Socratic dialogue <ArrowRight className="h-4 w-4" /></Button>
      </div>
    </section>
  )
}
