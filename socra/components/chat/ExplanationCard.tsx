"use client"

import { useId, useMemo, useRef, useState, useSyncExternalStore, type ComponentProps } from "react"
import { ArrowRight, BookOpen, ChevronDown, CircleAlert, Library, NotebookPen } from "lucide-react"
import type { Tokens } from "marked"
import { Button } from "@/components/ui/button"
import { ExplanationDocument } from "@/components/chat/ExplanationDocument"
import { EducationalDocumentCard } from "@/components/chat/EducationalDocumentCard"
import { StudyCode, StudyMarkdown, type StudyMarkdownPresentation } from "@/components/notebook/NotebookReply"
import { pdfPageUrl } from "@/lib/documents/pdf-page"
import { explanationV2, type UnitAction } from "@/lib/explanation-v2"
import type { DocumentUnitContext } from "@/lib/explanation-document"
import { explanationProgressKey, readExplanationProgress, writeExplanationProgress } from "@/lib/ai/explanation-progress"
import {
  canPairSetup, cardMarkdownBlocks, citationPageKey, coverageCopy, coverageHighlights, explanationCardLayout, groupGuideSections, uniqueCardCitations,
  type CardMarkdown, type CardProfile, type CardSectionKind,
} from "@/lib/ai/explanation-card-layout"
import { isEducationalDocument } from "@/lib/educational-document"
import type { ExerciseCitation, ExplanationPayload, PublicExplanation } from "@/lib/socra-ws"

const profileLabels: Partial<Record<CardProfile, string>> = {
  guide: "Walkthrough",
  math: "Mathematics",
  language: "Language lesson",
  research: "Research analysis",
}

const disclosureClass = "group/explanation print:[&::details-content]:[content-visibility:visible]"
const focusClass = "rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
const supportLabel = "text-[10px] font-semibold uppercase tracking-widest text-muted-foreground"
const callouts: Partial<Record<CardSectionKind, string>> = {
  answer: "border-primary/30 bg-muted/40",
  formula: "border-primary/30 bg-muted/40",
  researchQuestion: "border-primary/30 bg-muted/40",
  takeaway: "border-secondary bg-secondary/10",
  verification: "border-secondary bg-secondary/10",
  reference: "border-secondary bg-secondary/10",
  checkpoint: "border-secondary bg-secondary/10",
  troubleshooting: "border-tertiary bg-tertiary/10",
}

function PageLinks({ citations, compact = false }: { citations: ExerciseCitation[]; compact?: boolean }) {
  if (!citations.length) return null
  const groups = new Map<string, ExerciseCitation[]>()
  for (const citation of citations) {
    const key = citation.document_id || citation.filename
    const group = groups.get(key) ?? []
    group.push(citation)
    groups.set(key, group)
  }
  for (const group of groups.values()) group.sort((a, b) => (a.page_number ?? Infinity) - (b.page_number ?? Infinity))

  return <span className="inline-flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-xs">
    {[...groups.entries()].map(([key, group]) => {
      const filename = group[0].filename
      return <span key={key} className="inline-flex min-w-0 flex-wrap items-baseline gap-1">
        {(!compact || groups.size > 1 || !group.some(({ page_number }) => page_number)) &&
          <span className="min-w-0 text-muted-foreground [overflow-wrap:anywhere]">{filename}</span>}
        {group.map(({ document_id, page_number }) => page_number && (
          document_id
            ? <a key={page_number} className={`${focusClass} inline-flex items-center bg-muted px-1.5 py-0.5 font-medium text-foreground underline-offset-2 hover:underline`}
              href={pdfPageUrl(document_id, page_number)} target="_blank" rel="noopener noreferrer"
              onClick={compact ? (event) => event.stopPropagation() : undefined}
              aria-label={`${filename}, page ${page_number} (opens PDF in a new tab)`}>p. {page_number}</a>
            : <span key={page_number} className="px-1 text-muted-foreground">p. {page_number}</span>
        ))}
      </span>
    })}
  </span>
}

function CoverageNotice({ heading, content, citations }: { heading: string; content: string; citations: ExerciseCitation[] }) {
  const { summary, detail } = coverageCopy(heading, content)
  const highlights = coverageHighlights(detail)
  const count = /\((\d+)\)[.:]/.exec(content)?.[1]
  return <aside className="flex items-start gap-2.5 border-s-2 border-tertiary bg-tertiary/10 px-3 py-2.5">
    <CircleAlert className="mt-0.5 size-4 shrink-0 text-foreground" aria-hidden />
    <div className="min-w-0 flex-1">
      <details className={disclosureClass}>
        <summary className={`${focusClass} cursor-pointer text-sm font-semibold`}>
          <span dir="auto">{summary}</span>{count && <span className="ms-2 text-xs tabular-nums">({count})</span>}
          <span className="ms-2 text-xs font-normal text-muted-foreground print:hidden">Details</span>
          {highlights && <span dir="auto" className="mt-0.5 block text-xs font-normal text-muted-foreground">{highlights}</span>}
        </summary>
        <div className="mt-2 space-y-2 text-sm leading-relaxed" dir="auto">
          {heading && heading !== summary && <p className="font-medium">{heading}</p>}
          {detail && <StudyMarkdown content={detail} />}
          <PageLinks citations={citations} />
        </div>
      </details>
    </div>
  </aside>
}

function SourceExcerpts({ citations }: { citations: ExerciseCitation[] }) {
  return <ul className="mt-2 space-y-1.5">{citations.filter((citation) => citation.excerpt).map((citation, index) =>
    <li key={index} className="leading-relaxed [overflow-wrap:anywhere]">
      <span className="font-medium">{citation.filename}{citation.page_number ? ` · p. ${citation.page_number}` : ""}</span>
      <p dir="auto">{citation.excerpt}</p>
    </li>)}</ul>
}

type Checklist = StudyMarkdownPresentation["checklist"]

function SectionText({ text, kind, profile, checklist, sourced = false }: {
  text: CardMarkdown; kind: CardSectionKind | null; profile: CardProfile; checklist: Checklist
  sourced?: boolean
}) {
  const presentation: StudyMarkdownPresentation = { checklist, codeLineEnding: text.codeLineEnding, copyTables: true }
  const blocks = cardMarkdownBlocks(text.tokens, kind, profile)
  const renderBlock = (block: (typeof blocks)[number], index: number) => {
    const metricSummary = profile === "generic" && sourced && (kind === "metrics" || block.kind === "metrics")
    const markdown = <StudyMarkdown tokens={block.tokens} presentation={metricSummary ? { ...presentation, metricSummary } : presentation} />
    if (block.answer) return <details key={index} className={`${disclosureClass} rounded-lg bg-muted/40 px-3 py-2`}>
      <summary className={`${focusClass} cursor-pointer text-sm font-medium`}>Show answer
        <span className="sr-only"> ({block.tokens[0].type === "heading" ? (block.tokens[0] as Tokens.Heading).text : `item ${index + 1}`})</span>
      </summary>
      <div className="mt-2">{markdown}</div>
    </details>
    if (profile === "guide" && block.kind === "troubleshooting" && block.tokens.map(({ raw }) => raw).join("").length > 240) {
      const [heading, ...body] = block.tokens
      return <details key={index} className={`${disclosureClass} rounded-lg border border-tertiary bg-tertiary/10 p-3`}>
        <summary className={`${focusClass} cursor-pointer font-medium`}>{(heading as Tokens.Heading).text}</summary>
        <div className="mt-2"><StudyMarkdown tokens={body} presentation={presentation} /></div>
      </details>
    }
    const tone = block.kind && callouts[block.kind]
    return <div key={index} className={tone ? `min-w-0 rounded-e-lg border-s-2 p-3 ${tone}`
      : profile === "guide" && block.kind === "question" ? "min-w-0 border-t pt-3" : "min-w-0"}>{markdown}</div>
  }

  return <div className={`min-w-0 space-y-3 [&_div:has(>table)]:rounded-lg [&_div:has(>table)]:border [&_td]:min-w-20 [&_th]:min-w-20 ${
    kind === "derivation" ? "[&_ol>li+li]:border-t [&_ol>li]:py-2 [&_ol>li]:ps-2" : ""
  } ${profile === "guide" || profile === "generic" || profile === "compact"
    ? "[&_h4]:font-sans [&_h4]:text-sm [&_h5]:font-sans [&_h5]:text-sm [&_ol]:marker:font-semibold" : ""} ${
    profile === "compact" ? "[&_ul>li+li]:border-t [&_ul>li]:py-1.5 [&_ul>li]:marker:text-secondary" : ""
  }`}>
    {blocks.map((block, index) => {
      if (profile === "guide" && canPairSetup(blocks[index - 1], block)) return null
      if (profile === "guide" && canPairSetup(block, blocks[index + 1])) {
        return <div key={index} data-explanation-setup className="grid min-w-0 items-start gap-3 @min-[52rem]/card:grid-cols-2">
          <div className="min-w-0 rounded-lg border bg-muted/35 p-3">{renderBlock(block, index)}</div>
          {renderBlock(blocks[index + 1], index + 1)}
        </div>
      }
      if (!block.column) return renderBlock(block, index)
      if (blocks[index - 1]?.column) return null
      if (!blocks[index + 1]?.column) return renderBlock(block, index)
      return <div key={index} className="grid min-w-0 gap-2.5 @md/card:grid-cols-2">
        {blocks.slice(index, index + 2).map((column, columnIndex) =>
          <div key={columnIndex} className="min-w-0 rounded-lg border bg-muted/35 p-3">{renderBlock(column, columnIndex)}</div>)}
      </div>
    })}
  </div>
}

function ExplanationSection({ section, profile, collapse, open, checklist, number, children, phaseSummary, phaseSources, nested = false }: {
  section: ReturnType<typeof explanationCardLayout>["sections"][number]
  profile: CardProfile
  collapse: boolean
  open: boolean
  checklist: Checklist
  number?: number
  children?: React.ReactNode
  phaseSummary?: string
  phaseSources?: ExerciseCitation[]
  nested?: boolean
}) {
  const { heading, kind, text, language, code, walkthrough, citations, summary } = section
  const guide = profile === "guide"
  const disclosure = collapse && !!heading && (guide || kind !== "phase")
  const headerSources = disclosure || guide && !!heading
  const tone = kind && callouts[kind]
  const sourceReference = kind === "reference" && citations.some((citation) => citation.document_id && citation.page_number && citation.excerpt)
  const hasText = text.tokens.some((token) => token.type !== "space")
  const onlyHeading = !hasText && !code && !walkthrough.length && !citations.length
  if (onlyHeading && !heading) return null

  const body = <div className={`min-w-0 space-y-3 text-sm leading-relaxed sm:text-[15px] ${nested ? "pb-1.5" : "pb-4 sm:pb-5"} ${guide && disclosure ? "px-3 sm:px-4" : ""}`} dir="auto">
    {(hasText || sourceReference) && <div className={tone ? `min-w-0 rounded-e-lg border-s-2 p-3 ${tone}` : "min-w-0"}>
      {sourceReference && <p className={supportLabel + " mb-1"}>Source reference</p>}
      <SectionText text={text} kind={kind} profile={profile} checklist={checklist}
        sourced={citations.some(({ document_id, page_number }) => !!document_id && !!page_number)} />
    </div>}
    {code && <StudyCode value={code} language={language} />}
    {walkthrough.map((item, index) => <div className="space-y-2" key={index}>
      {item.code && <StudyCode value={item.code} language={language} />}
      {item.explanation?.trim() && <StudyMarkdown content={item.explanation} />}
    </div>)}
    {!!citations.length && <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
      {!headerSources && <PageLinks citations={citations} compact />}
      {citations.some((citation) => citation.excerpt) && <details className={`${disclosureClass} text-xs text-muted-foreground`}>
        <summary className={`${focusClass} cursor-pointer`}>{kind === "checkpoint" ? "Screenshot source" : "Section excerpts"}</summary>
        <SourceExcerpts citations={citations} />
      </details>}
    </div>}
    {children && <div className="space-y-3">{children}</div>}
  </div>

  if (kind === "phase" && onlyHeading && !disclosure) return <h4 dir="auto" className="rounded-lg bg-muted px-3 py-2 text-sm font-semibold">{heading}</h4>

  return disclosure && (!onlyHeading || children)
    ? <details open={open} data-explanation-collapse className={`${disclosureClass} ${guide ? "rounded-lg border bg-muted/20" : "border-t first:border-t-0"}`}>
      <summary className={`${focusClass} cursor-pointer list-none hover:bg-muted/40 [&::-webkit-details-marker]:hidden ${guide ? "px-3 py-2.5 sm:px-4" : "py-3.5"}`}>
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          {number !== undefined && <span aria-hidden className="min-w-6 rounded bg-muted px-1.5 py-0.5 text-center text-xs font-semibold tabular-nums">{number}</span>}
          <span dir="auto" className="min-w-32 flex-1 font-semibold [overflow-wrap:anywhere]">{heading}</span>
          <PageLinks citations={phaseSources ?? citations} compact />
          <ChevronDown className="ms-auto size-4 shrink-0 text-muted-foreground group-open/explanation:rotate-180 print:hidden" aria-hidden />
        </span>
        {guide && (summary || phaseSummary) && <span dir="auto" className="mt-0.5 block truncate ps-8 text-xs text-muted-foreground group-open/explanation:hidden print:hidden">
          {summary || phaseSummary}
        </span>}
      </summary>
      {body}
    </details>
    : <section className={profile === "compact" ? "" : "border-t first:border-t-0"}>
      {heading && <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-2">
        <h4 dir="auto" className={`font-semibold [overflow-wrap:anywhere] ${profile === "compact" ? supportLabel + " mb-2" : profile === "generic" ? supportLabel + " py-3.5" : nested ? "py-2 text-sm" : "py-3.5"}`}>{heading}</h4>
        {headerSources && <PageLinks citations={citations} compact />}
      </div>}
      {!onlyHeading && body}
    </section>
}

const subscribeToHydration = () => () => {}

type CardProps = {
  explanation: ExplanationPayload
  ownerId?: string
  explanationId?: string
  onDiscuss?: (question: string) => void
  onContinueCourse?: (from: string, requestId: string, label: string) => void
  onUnitAction?: (from: string, action: UnitAction, label: string) => void
  unitContext?: DocumentUnitContext
  usedUnitRequests?: ReadonlySet<string>
  coursePartLinks?: Array<{ part: number; messageId: string }>
  onSaveToLibrary?: (explanation: ExplanationPayload) => void
  notebookCapture?: Pick<ComponentProps<"button">, "onPointerDown" | "onClick">
  disabled?: boolean
  readOnly?: boolean
}

export function ExplanationCard(props: CardProps) {
  const { explanation, disabled, notebookCapture, onSaveToLibrary, readOnly } = props
  if (isEducationalDocument(explanation)) return <EducationalDocumentCard document={explanation}
    disabled={disabled} notebookCapture={readOnly ? undefined : notebookCapture}
    onSaveToLibrary={!readOnly && onSaveToLibrary ? () => onSaveToLibrary(explanation) : undefined} />
  return <LegacyExplanationCard {...props} explanation={explanation} />
}

function LegacyExplanationCard({ explanation, onDiscuss, onContinueCourse, onUnitAction, unitContext, usedUnitRequests,
  onSaveToLibrary, notebookCapture, disabled = false, readOnly = false, ownerId, explanationId, coursePartLinks }:
  Omit<CardProps, "explanation"> & { explanation: PublicExplanation }) {
  const id = useId()
  const sectionList = useRef<HTMLDivElement>(null)
  const [taskChecks, setTaskChecks] = useState<{ key: string; checks: Record<number, boolean> }>()
  const hydrated = useSyncExternalStore(subscribeToHydration, () => true, () => false)
  const structured = useMemo(() => explanationV2(explanation), [explanation])
  const layout = useMemo(() => explanationCardLayout(structured
    ? { ...explanation, sections: [], definition: "", intuition: "", course_example: "", citations: [], coverage_notices: [] }
    : explanation), [explanation, structured])
  const { profile, notices, citations, definition, intuition, example, sections, title, collapsible } = layout
  const taskOriented = profile === "guide" || profile === "generic" && sections.some(({ code, text }) =>
    code || text.tokens.some((token) => token.type === "code"))
  const tasks = useMemo(() => taskOriented
    ? [definition, intuition, example, ...sections.map(({ text }) => text)].flatMap(({ tasks }) => [...tasks])
    : [], [definition, example, intuition, sections, taskOriented])
  const storageKey = tasks.length ? explanationProgressKey(ownerId, explanationId) : ""
  const savedChecks = useMemo(() => hydrated ? readExplanationProgress(storageKey, tasks.length) : {},
    [hydrated, storageKey, tasks.length])
  const checks = useMemo(() => taskChecks?.key === storageKey ? taskChecks.checks : savedChecks,
    [savedChecks, storageKey, taskChecks])
  const completed = tasks.filter((_, index) => checks[index] ?? false).length
  const positions = useMemo(() => new Map(tasks.map((item, index) => [item, index])), [tasks])
  const checklist: Checklist = taskOriented ? (item) => {
    const index = positions.get(item)
    if (index === undefined) return
    return {
      checked: checks[index] ?? false,
      toggle: (checked) => {
        const next = { ...checks, [index]: checked }
        setTaskChecks({ key: storageKey, checks: next })
        writeExplanationProgress(storageKey, next)
      },
    }
  } : undefined
  const contextualSources = [...sections, ...notices].flatMap((section) => section.citations)
  const placedPages = new Set(contextualSources.map(citationPageKey))
  const extraPages = citations.filter((citation) => !placedPages.has(citationPageKey(citation)))
  const extraExcerpts = citations.filter((citation) => citation.excerpt && !contextualSources.some((source) =>
    citationPageKey(source) === citationPageKey(citation) && source.excerpt?.trim() === citation.excerpt?.trim()))
  const initiallyOpen = sections.filter(({ kind }) => kind !== "phase").slice(0, profile === "research" ? 3 : 2)
  const guideGroups = profile === "guide" && collapsible ? groupGuideSections(sections) : null
  const setSectionsOpen = (open: boolean) => {
    sectionList.current?.querySelectorAll<HTMLDetailsElement>("[data-explanation-collapse]").forEach((details) => { details.open = open })
  }
  const french = explanation.language === "French"
  const course = explanation.course_progress
  const modeLabel = explanation.presentation === "revision_sheet" ? (french ? "Fiche de révision" : "Revision sheet")
    : explanation.presentation === "beginner" ? (french ? "Les bases du cours" : "Course foundations")
    : explanation.presentation === "full_course" ? (french ? "Étude du cours" : "Course study")
    : explanation.presentation === "standard" && french ? "Explication du cours" : undefined
  const label = structured ? (french ? "Explication" : "Explanation")
    : modeLabel ?? profileLabels[profile] ?? (profile === "generic" ? "Course explanation" : undefined)
  const continuationLabel = french ? `Continuer avec la partie ${(course?.part ?? 0) + 1}`
    : `Continue with part ${(course?.part ?? 0) + 1}`
  const coverageLabels = french ? {
    covered: "Traité", partial: "Partiel", missing: "Manquant", unverifiable: "Non vérifiable", not_yet_generated: "À venir",
  } : {
    covered: "Covered", partial: "Partial", missing: "Missing", unverifiable: "Unverifiable", not_yet_generated: "Not yet generated",
  }
  const from = course?.request_id
  const unitAction = !readOnly && from && onUnitAction
    ? (action: UnitAction, actionLabel: string) => onUnitAction(from, action, actionLabel) : undefined
  const compact = profile === "compact"
  const compactHeading = compact && !title && !definition.tokens.length && !intuition.tokens.length && sections.length === 1
    ? sections[0].heading : ""
  const sourceFooter = (extraPages.length > 0 || extraExcerpts.length > 0) && <footer className="space-y-1.5 border-t py-2.5">
    {!!extraPages.length && <div className="flex flex-wrap items-baseline gap-2 text-xs text-muted-foreground">
      <span>Source</span><PageLinks citations={extraPages} compact />
    </div>}
    {extraExcerpts.length > 0 && <details className={`${disclosureClass} text-xs text-muted-foreground`}>
      <summary className={`${focusClass} ${supportLabel} cursor-pointer`}>{french ? "Extraits des sources" : "Source excerpts"} ({extraExcerpts.length})</summary>
      <SourceExcerpts citations={extraExcerpts} />
    </details>}
  </footer>

  return <article aria-labelledby={id} data-explanation-card={structured ? "structured" : profile}
    className="@container/card mb-4 w-full min-w-0 max-w-full rounded-2xl border border-primary/20 bg-card text-card-foreground shadow-sm [&_:is(p,blockquote,ol,ul):not(:has(pre,table))]:max-w-[46rem] print:border-0 print:shadow-none">
    <div className="space-y-3 px-4 pt-4 sm:px-6 sm:pt-5 print:px-0">
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0" id={id}>
          {label && title && <p className={supportLabel + " mb-1"}>{label}</p>}
          {title ? <div dir="auto" className="[&_h3]:font-sans [&_h3]:text-xl [&_h3]:tracking-tight sm:[&_h3]:text-2xl">
            <StudyMarkdown tokens={[title]} presentation={{}} />
          </div> : <h3 className="flex items-center gap-2 text-base font-semibold">
            <BookOpen className="size-4 shrink-0 text-primary" aria-hidden />{label || compactHeading || "Course explanation"}
          </h3>}
        </div>
        {!readOnly && (onSaveToLibrary || notebookCapture) && <div className="flex flex-wrap gap-1.5 print:hidden">
          {onSaveToLibrary && <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => onSaveToLibrary(explanation)}>
            <Library className="size-4" aria-hidden />Save to Library
          </Button>}
          {notebookCapture && <Button type="button" size="sm" variant="outline" {...notebookCapture}>
            <NotebookPen className="size-4" aria-hidden />Save to Notebook
          </Button>}
        </div>}
      </header>
      {!structured && notices.length > 0 && <div className="space-y-1.5" role="status">
        {notices.map((notice, index) => <CoverageNotice key={index} {...notice} />)}
      </div>}
      {!structured && !!definition.tokens.length && <div dir="auto" className="text-sm leading-relaxed sm:text-base">
        <SectionText text={definition} kind={null} profile={profile} checklist={checklist} />
      </div>}
      {!structured && !!intuition.tokens.length && <div dir="auto" className="text-sm leading-relaxed sm:text-[15px]">
        <StudyMarkdown tokens={intuition.tokens} presentation={{ checklist, codeLineEnding: intuition.codeLineEnding }} />
      </div>}
    </div>
    {structured && <ExplanationDocument explanation={structured} french={french} context={unitContext}
      onAction={unitAction} usedRequests={usedUnitRequests} disabled={disabled} ownerId={readOnly ? undefined : ownerId}
      onDiscuss={readOnly ? undefined : onDiscuss} />}
    {!structured && course && <div className="mx-4 space-y-2 border-t py-3 text-sm sm:mx-6">
      <h3 className="font-medium">{french ? `Partie ${course.part} sur ${course.total_parts}` : `Part ${course.part} of ${course.total_parts}`}</h3>
      {!!coursePartLinks?.length && <nav aria-label={french ? "Parties précédentes" : "Previous parts"} className="flex flex-wrap gap-3 print:hidden">
        {coursePartLinks.map(({ part, messageId }) => <a className={`${focusClass} underline`} key={part}
          href={`#message-${encodeURIComponent(messageId)}`}>{french ? `Partie ${part}` : `Part ${part}`}</a>)}
      </nav>}
      {course.inventory_uncertain && <p className="text-xs text-muted-foreground">{french
        ? "La couverture porte sur les sections identifiées dans le plan du cours."
        : "Coverage applies to the sections identified in the Course Map."}</p>}
      {!!course.sections.length && <details className={disclosureClass} open>
        <summary className={`${focusClass} cursor-pointer`}>{french ? "Couverture et sections restantes" : "Coverage and remaining sections"}</summary>
        <ol className="mt-2 list-decimal space-y-1 ps-5">
          {course.sections.map((section) => <li key={section.id} dir="auto">
            {section.title || (french ? "Section non identifiée" : "Unidentified section")}
            {` (p. ${section.start}${section.end === section.start ? "" : `–${section.end}`}) · ${coverageLabels[section.status]}`}
          </li>)}
        </ol>
      </details>}
      {!course.next_request_id && course.part < course.total_parts && <p className="text-xs text-muted-foreground">
        {french ? "La suite nécessite un index complet du PDF." : "Continuing requires a complete PDF index."}
      </p>}
      {onContinueCourse && course.request_id && course.next_request_id && <Button type="button" size="sm" variant="outline"
        disabled={disabled} className="print:hidden"
        onClick={() => onContinueCourse(course.request_id!, course.next_request_id!, continuationLabel)}>
        {continuationLabel}
      </Button>}
    </div>}
    {!structured && (tasks.length > 0 || collapsible) && <div className="mt-2 flex flex-wrap items-center justify-between gap-2 px-4 sm:px-6 print:hidden">
      {tasks.length > 0 && <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <progress aria-label="Checklist progress" value={completed} max={tasks.length}
          className="h-2 w-20 appearance-none overflow-hidden rounded-full bg-muted [&::-moz-progress-bar]:bg-primary [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-primary" />
        <span aria-live="polite">{completed} of {tasks.length} tasks checked</span>
      </div>}
      {collapsible && <div className="ms-auto flex flex-wrap gap-1">
        <Button type="button" size="sm" variant="ghost" aria-controls={`${id}-sections`} onClick={() => setSectionsOpen(true)}>Expand all</Button>
        <Button type="button" size="sm" variant="ghost" aria-controls={`${id}-sections`} onClick={() => setSectionsOpen(false)}>Collapse all</Button>
      </div>}
    </div>}
    {!structured && <div className={`px-4 pb-4 sm:px-6 sm:pb-5 print:px-0 ${compact ? "pt-4" : "pt-2"}`}>
      {sections.length > 0 && <div id={`${id}-sections`} className={`min-w-0 ${guideGroups ? "space-y-1.5" : ""}`} ref={sectionList}>
        {guideGroups ? guideGroups.map(({ section, children, phaseLabel }, index) => <div key={section.index}>
          {phaseLabel && <h4 dir="auto" className={supportLabel + " mb-1 bg-muted/45 px-3 py-2"}>{phaseLabel}</h4>}
          <ExplanationSection
          section={section} profile={profile} collapse open={index === 0} checklist={checklist} number={index + 1}
          phaseSources={children.length ? uniqueCardCitations([...section.citations, ...children.flatMap((child) => child.citations)]) : undefined}
          phaseSummary={children[0]?.summary || children[0]?.heading}>
          {children.length > 0 && children.map((child) => <ExplanationSection key={child.index}
            section={child} profile={profile} collapse={false} open={false} checklist={checklist} nested />)}
        </ExplanationSection></div>) : sections.map((section) => <ExplanationSection key={section.index}
          section={compactHeading ? { ...section, heading: "" } : section} profile={profile}
          collapse={collapsible} open={initiallyOpen.includes(section)} checklist={checklist} />)}
      </div>}
      {!!example.tokens.length && <section dir="auto" className="mb-4 text-sm leading-relaxed sm:text-[15px]">
        <h4 className={supportLabel + " mb-1"}>{french ? "Exemple du cours" : "From your course"}</h4>
        <SectionText text={example} kind="example" profile={profile} checklist={checklist} />
      </section>}
      {layout.brief && sourceFooter}
      {!!explanation.common_pitfalls?.length && <SupportingMaterial title={french ? "Pièges fréquents" : "Common pitfalls"} collapsed={layout.brief} count={explanation.common_pitfalls.length}>
        <ul className="mt-1 list-disc space-y-1 ps-5 text-sm leading-relaxed">{explanation.common_pitfalls.map((item, index) =>
          <li key={index} dir="auto"><StudyMarkdown content={item} /></li>)}</ul>
      </SupportingMaterial>}
      {!!explanation.check_question?.trim() && <SupportingMaterial title={french ? "Vérifier sa compréhension" : "Check your understanding"} collapsed={layout.brief}
        headingId={id + "-check"} count={1}>
        <div dir="auto"><StudyMarkdown content={explanation.check_question} /></div>
        {!readOnly && onDiscuss && <Button type="button" variant="outline" className="h-auto min-h-8 whitespace-normal py-1 text-start print:hidden"
          onClick={() => onDiscuss(explanation.check_question)} disabled={disabled}>
          {french ? "En discuter dans un dialogue socratique" : "Discuss in Socratic dialogue"} <ArrowRight className="size-4" aria-hidden />
        </Button>}
      </SupportingMaterial>}
      {!layout.brief && sourceFooter}
    </div>}
  </article>
}

function SupportingMaterial({ title, headingId, collapsed, count, children }: {
  title: string; headingId?: string; collapsed: boolean; count: number; children: React.ReactNode
}) {
  if (collapsed) return <details className={`${disclosureClass} border-t py-2.5 text-sm`}>
    <summary className={`${focusClass} cursor-pointer font-medium`}>
      {title}<span className="ms-2 text-xs text-muted-foreground">({count})</span>
    </summary>
    <div className="mt-2 space-y-2">{children}</div>
  </details>
  return <section aria-labelledby={headingId} className="mb-4 space-y-2 border-t pt-3 text-sm leading-relaxed">
    <h4 id={headingId} className={supportLabel}>{title}</h4>
    {children}
  </section>
}
