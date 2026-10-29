"use client"

import { useState } from "react"
import { ArrowRight, BookOpen, Check, Copy, Lightbulb, Library, NotebookPen } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { PublicExplanation } from "@/lib/socra-ws"

export function ExplanationCard({ explanation, onDiscuss, onSaveToLibrary, onSaveToNotebook, disabled = false, readOnly = false }: {
  explanation: PublicExplanation
  onDiscuss?: (question: string) => void
  onSaveToLibrary?: (explanation: PublicExplanation) => void
  onSaveToNotebook?: (explanation: PublicExplanation) => void
  disabled?: boolean
  readOnly?: boolean
}) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null)

  async function copyText(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedKey(key)
      window.setTimeout(() => setCopiedKey((current) => current === key ? null : current), 1800)
    } catch {
      setCopiedKey(null)
    }
  }

  function renderSectionContent(content: string, sectionIndex: number) {
    const codeFence = /```([\w+-]*)\s*\n([\s\S]*?)```/g
    const parts: Array<{ type: "text" | "code"; value: string; language?: string }> = []
    let lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = codeFence.exec(content)) !== null) {
      if (match.index > lastIndex) parts.push({ type: "text", value: content.slice(lastIndex, match.index).trim() })
      parts.push({ type: "code", value: match[2].replace(/\n$/, ""), language: match[1] || undefined })
      lastIndex = codeFence.lastIndex
    }
    if (lastIndex < content.length) parts.push({ type: "text", value: content.slice(lastIndex).trim() })
    if (!parts.length) parts.push({ type: "text", value: content })

    return <div className="space-y-3">{parts.map((part, partIndex) => part.type === "code" ? (
      <div key={`code-${partIndex}`} className="overflow-hidden rounded-lg border border-border/70 bg-muted/50">
        <div className="flex items-center justify-between border-b border-border/70 px-3 py-2">
          <span className="text-xs text-muted-foreground">{part.language || "Code cell"}</span>
          <Button type="button" variant="ghost" size="sm" className="h-7 gap-1.5 px-2" onClick={() => copyText(`${sectionIndex}-${partIndex}`, part.value)}>
            {copiedKey === `${sectionIndex}-${partIndex}` ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copiedKey === `${sectionIndex}-${partIndex}` ? "Copied" : "Copy code"}
          </Button>
        </div>
        <pre className="overflow-x-auto p-4 text-xs leading-relaxed"><code>{part.value}</code></pre>
      </div>
    ) : part.value ? <p key={`text-${partIndex}`} className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{part.value}</p> : null)}</div>
  }

  return (
    <section className="mx-4 mb-4 space-y-5 rounded-2xl border border-primary/20 bg-card p-5 shadow-sm sm:mx-6 sm:p-6" aria-live="polite">
      <div className="flex items-center gap-2 text-primary">
        <BookOpen className="h-5 w-5" />
        <h3 className="text-lg font-semibold text-foreground">Course explanation</h3>
      </div>
      {!readOnly && <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" className="gap-1.5" onClick={() => onSaveToLibrary?.(explanation)}><Library className="h-4 w-4"/>Save to Library</Button><Button type="button" size="sm" variant="outline" className="gap-1.5" onClick={() => onSaveToNotebook?.(explanation)}><NotebookPen className="h-4 w-4"/>Add to Notebook</Button></div>}
      {explanation.definition ? <div className="space-y-2"><h4 className="text-sm font-semibold">Definition</h4><p className="text-sm leading-relaxed text-muted-foreground">{explanation.definition}</p></div> : null}
      {explanation.intuition ? <div className="space-y-2"><h4 className="text-sm font-semibold">Intuition</h4><p className="text-sm leading-relaxed text-muted-foreground">{explanation.intuition}</p></div> : null}
      {explanation.sections?.length ? <div className="space-y-4">{explanation.sections.map((section, index) => {
        const copyValue = section.code || section.content
        const copyKey = section.code ? `solution-${index}` : `section-${index}`
        return <section key={`${section.heading}-${index}`} className="space-y-3 rounded-xl border border-border/60 p-4">
          <div className="flex items-start justify-between gap-3"><h4 className="font-semibold text-foreground">{section.heading}</h4><Button type="button" variant="ghost" size="sm" className="h-7 shrink-0 gap-1.5 px-2" onClick={() => copyText(copyKey, copyValue)}>{copiedKey === copyKey ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copiedKey === copyKey ? "Copied" : section.code ? "Copy solution code" : "Copy section"}</Button></div>
          {section.code ? <div className="overflow-hidden rounded-lg border border-border/70 bg-muted/50"><div className="border-b border-border/70 px-3 py-2"><span className="text-xs text-muted-foreground">Complete code for this exercise{section.code_language ? ` · ${section.code_language}` : ""}</span></div><pre className="overflow-x-auto p-4 text-xs leading-relaxed"><code>{section.code}</code></pre></div> : null}
          {section.walkthrough?.length ? <div className="space-y-4">{section.walkthrough.map((item, itemIndex) => {
            const key = `walkthrough-${index}-${itemIndex}`
            return <div key={key} className="space-y-2 rounded-lg bg-muted/25 p-3">
              <div className="flex items-start justify-between gap-3 rounded-md border border-border/70 bg-muted/60 px-3 py-2">
                <pre className="overflow-x-auto text-xs leading-relaxed text-foreground"><code>{item.code}</code></pre>
                <Button type="button" variant="ghost" size="sm" className="h-7 shrink-0 gap-1.5 px-2" onClick={() => copyText(key, item.code)}>{copiedKey === key ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copiedKey === key ? "Copied" : "Copy code"}</Button>
              </div>
              <p className="px-1 text-sm leading-relaxed text-muted-foreground">{item.explanation}</p>
            </div>
          })}</div> : null}
          {section.content ? renderSectionContent(section.content, index) : null}
        </section>
      })}</div> : null}
      {explanation.course_example ? <div className="space-y-2"><h4 className="text-sm font-semibold">From your course</h4><p className="text-sm leading-relaxed text-muted-foreground">{explanation.course_example}</p></div> : null}
      {explanation.common_pitfalls?.length ? <div className="rounded-xl bg-muted/40 p-4"><h4 className="flex items-center gap-2 text-sm font-semibold"><Lightbulb className="h-4 w-4 text-primary" />Common pitfalls</h4><ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-muted-foreground">{explanation.common_pitfalls.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
      <details className="rounded-xl border border-border/70 px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium">Course sources ({explanation.citations.length})</summary>
        <ul className="mt-3 space-y-3 text-sm">{explanation.citations.map((citation, index) => <li key={`${citation.document_id}-${citation.page_number}-${index}`}><p className="font-medium">{citation.filename} · page {citation.page_number ?? "page unavailable"}</p><p className="mt-1 text-muted-foreground">{citation.excerpt ? `“${citation.excerpt}”` : "The source page is cited, but the excerpt is unavailable."}</p></li>)}</ul>
      </details>
      {explanation.check_question ? <div className="rounded-xl border border-primary/15 bg-primary/5 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Check your understanding</p>
        <p className="mt-2 text-sm font-medium leading-relaxed">{explanation.check_question}</p>
        {!readOnly && <Button className="mt-4 gap-2" onClick={() => onDiscuss?.(explanation.check_question)} disabled={disabled}>Discuss this question in Socratic dialogue <ArrowRight className="h-4 w-4" /></Button>}
      </div> : null}
    </section>
  )
}
