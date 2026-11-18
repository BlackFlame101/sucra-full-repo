"use client"

import { useId, useRef, type ReactNode, type SyntheticEvent } from "react"
import { ChevronDown } from "lucide-react"
import { ExplanationUnit, unitCoverageLabel, unitVerificationLabel } from "@/components/chat/ExplanationUnit"
import { PdfCitation } from "@/components/documents/PdfCitation"
import { Button } from "@/components/ui/button"
import { documentActionLabel, explanationDocument, type DocumentShell, type DocumentUnit,
  type DocumentUnitContext } from "@/lib/explanation-document"
import { explanationUnits, unitPresentation, type ExplanationV2, type UnitAction } from "@/lib/explanation-v2"
import { lexStudyMarkdown } from "@/lib/notebook/document"
import { ExplanationRunStatus, hasBudgetLimit, lifecycleText } from "@/components/chat/LiveExplanation"
import type { UnitActivityScope } from "@/components/chat/UnitActivity"

const chip = "rounded-md border px-2 py-0.5 text-xs text-muted-foreground"
const controls = "min-w-0 flex flex-wrap items-center gap-2"

type DocumentModel = ReturnType<typeof explanationDocument>

function syncDisclosure(event: SyntheticEvent<HTMLDetailsElement>) {
  const details = event.currentTarget
  details.querySelector(":scope > summary")?.setAttribute("aria-expanded", String(details.open))
}

function titleOf(unit: DocumentUnit) {
  return unit.output?.title || unit.progress?.title || unit.identity?.title
}

function referenceOf(unit: DocumentUnit) {
  return unit.identity?.label || titleOf(unit)
}

function unitStatus(unit: DocumentUnit, french: boolean) {
  if (unit.nonTeaching) return
  const coverage = unit.liveCoverage ?? unit.progress?.status ?? unit.output?.coverage
  const gap = Boolean(unit.progress?.unverifiable_source.length || unit.output?.unverifiable_source.length)
  const missing = Boolean(unit.progress?.missing_item_ids.length || unit.output?.missing_item_ids.length)
  if (unit.excluded) return unit.progress?.scope_reason === "exercise_excluded"
    ? (french ? "Ignoré à votre demande" : "Skipped at your request")
    : (french ? "Hors demande" : "Out of scope")
  return unitCoverageLabel(coverage, unitPresentation(unit.identity?.kind), french, gap || missing)
    ?? (gap ? (french ? "Source non vérifiable" : "Unverifiable source") : undefined)
}

function UnitRow({ unit, model, id, french, open, historical, activity, onDiscuss }: {
  unit: DocumentUnit; model: DocumentModel; id: string; french: boolean; open: boolean; historical?: boolean
  activity?: UnitActivityScope
  onDiscuss?: (question: string) => void
}) {
  historical = historical || unit.stale
  const status = historical ? (french ? "Version historique" : "Historical version")
    : unit.provisional ? (french ? "Provisoire" : "Provisional") : unitStatus(unit, french)
  const sourceWarning = french ? "Source non vérifiable" : "Unverifiable source"
  const hasSourceGap = Boolean(unit.progress?.unverifiable_source.length || unit.output?.unverifiable_source.length)
    && status !== sourceWarning
  const lifecycle = lifecycleText(unit.lifecycle ?? (unit.checking ? "checking"
    : !historical && unit.corrections?.length ? "corrected" : undefined), french)
  const start = unit.identity?.start ?? unit.progress?.pages[0]
  const end = unit.identity?.end ?? unit.progress?.pages[1]
  const dependencies = unit.dependencies.flatMap((id) => {
    const dependency = model.units.get(id)
    const label = dependency && referenceOf(dependency)
    return label ? [label] : []
  })
  const lab = model.shell === "lab" && unit.identity?.kind === "lab_step"
  const commands = lab ? unit.output?.blocks.filter((block) => block.kind === "code" ||
    (block.kind === "command_or_ui" && lexStudyMarkdown(block.text).some((token) => token.type === "code"))).length : 0
  const checkpoints = lab ? unit.output?.blocks.filter(({ kind }) => kind === "checkpoint").length : 0
  const result = model.results.find((fact) => fact.unitId === unit.id)
  const heading = <span className="min-w-0 flex-1 [overflow-wrap:anywhere] sm:basis-36" dir="auto">
    {unit.identity?.label && <span className="me-2 whitespace-nowrap text-xs text-muted-foreground">{unit.identity.label}</span>}
    <span className="font-medium">{titleOf(unit)}</span>
  </span>
  const expandable = unit.excluded ? undefined : unit.output ?? unit.history[0]?.output
  const hasPage = typeof start === "number" && Number.isSafeInteger(start) && start > 0
  const row = <span className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-x-3">
    {heading}
    {(result || dependencies.length || commands || checkpoints || hasPage || status || lifecycle || hasSourceGap) && <span
      className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1 [overflow-wrap:anywhere]">
      {result && <span className="text-xs tabular-nums">{result.value}{result.measure && ` ${result.measure}`}</span>}
      {dependencies.length > 0 && <span className={chip}>{french ? "Utilise " : "Uses "}{dependencies.join(", ")}</span>}
      {!!commands && <span className={chip}>{commands} {french
        ? (commands === 1 ? "bloc de commande" : "blocs de commande") : (commands === 1 ? "command block" : "command blocks")}</span>}
      {!!checkpoints && <span className={chip}>{checkpoints} {french
        ? (checkpoints === 1 ? "point de contrôle" : "points de contrôle") : (checkpoints === 1 ? "checkpoint" : "checkpoints")}</span>}
      {hasPage && (!expandable && !historical && unit.documentId
        ? <span className="text-xs"><PdfCitation documentId={unit.documentId} page={start} filename="PDF" /></span>
        : <span className={chip}>p. {start}{end && end > start ? `–${end}` : ""}</span>)}
      {status && <span className={chip}>{status}</span>}
      {hasSourceGap && <span className={chip}>{sourceWarning}</span>}
      {lifecycle && <span className={chip}>{lifecycle}</span>}
    </span>}
  </span>
  const rowStyle = "flex min-w-0 items-start gap-2 px-3 py-2 text-sm"
  if (expandable) {
    const archived = !unit.output ? unit.history[0] : undefined
    return <details open={open || undefined} id={id} data-document-unit={unit.id} data-expandable-unit onToggle={syncDisclosure}
      className="group/unit min-w-0 rounded-lg border open:bg-muted/20">
      <summary aria-controls={`${id}-body`} aria-expanded={open} className={`${rowStyle} min-h-11 cursor-pointer list-none focus-visible:outline-2 focus-visible:outline-ring`}>
        {row}<ChevronDown aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground group-open/unit:rotate-180" />
      </summary>
      <div id={`${id}-body`}><ExplanationUnit output={expandable} identity={archived?.identity ?? unit.identity}
        progress={archived ? undefined : unit.progress} documentId={historical || archived ? undefined : unit.documentId}
        corrections={archived?.change_log ?? unit.corrections} french={french} historical={historical || !!archived} embedded
        activity={activity} provisional={unit.provisional} stage={archived?.stage ?? unit.stage}
        history={archived ? unit.history.slice(1) : unit.history} onDiscuss={onDiscuss} />
        {unit.provisionalVersion && <details className="mx-3 mb-3 rounded-lg border">
          <summary className="min-h-11 cursor-pointer px-3 py-2">{french ? "Approfondissement provisoire" : "Provisional follow-up"}</summary>
          <ExplanationUnit output={unit.provisionalVersion.output} identity={unit.identity}
            documentId={unit.documentId} french={french} provisional embedded />
        </details>}
      </div>
    </details>
  }
  return <div id={id} data-document-unit={unit.id} className={`${rowStyle} flex-col rounded-lg border border-dashed`}>
    {row}
  </div>
}

function UnitGroup({ title, children, french, expandable, pages, coverage }: {
  title?: string; children: ReactNode; french: boolean; expandable: boolean; pages?: string; coverage?: string
}) {
  const content = useRef<HTMLDivElement>(null)
  const disclosure = useRef<HTMLDetailsElement>(null)
  const groupId = useId()
  if (!title) return <div className="space-y-2">{children}</div>
  function expand(open: boolean) {
    if (disclosure.current) disclosure.current.open = true
    content.current?.querySelectorAll<HTMLDetailsElement>("details[data-expandable-unit]").forEach((unit) => { unit.open = open })
  }
  return <details open ref={disclosure} onToggle={syncDisclosure} className="min-w-0 border-t pt-2">
    <summary aria-controls={groupId} aria-expanded="true" className="min-h-11 cursor-pointer py-2 font-semibold focus-visible:outline-2 focus-visible:outline-ring">{title}
      {pages && <span className={`ms-2 font-normal ${chip}`}>{pages}</span>}
      {coverage && <span className={`ms-2 font-normal ${chip}`}>{coverage}</span>}
    </summary>
    <div className="mt-2 space-y-2" ref={content} id={groupId}>
      {expandable && <div className={controls}>
        <Button className="min-h-11 sm:min-h-8" size="sm" variant="ghost" onClick={() => expand(true)}>{french ? "Tout développer" : "Expand all"}</Button>
        <Button className="min-h-11 sm:min-h-8" size="sm" variant="ghost" onClick={() => expand(false)}>{french ? "Tout réduire" : "Collapse all"}</Button>
      </div>}
      {children}
    </div>
  </details>
}

function countLabel(shell: DocumentShell, french: boolean, explained: number, total: number) {
  if (shell === "exercises") return french ? `${explained} questions sur ${total} répondues` : `${explained} of ${total} questions answered`
  if (shell === "lab") return french ? `${explained} sur ${total} étapes expliquées` : `${explained} of ${total} steps explained`
  return french ? `${explained} sur ${total} unités expliquées` : `${explained} of ${total} units explained`
}

const depthLabels: Record<string, [string, string]> = {
  summary: ["Synthèse", "Summary"], standard: ["Profondeur standard", "Standard depth"], exhaustive: ["Profondeur exhaustive", "Exhaustive depth"],
}
const levelLabels: Record<string, [string, string]> = {
  beginner: ["Niveau débutant", "Beginner level"], intermediate: ["Niveau intermédiaire", "Intermediate level"],
  standard: ["Niveau standard", "Standard level"], advanced: ["Niveau avancé", "Advanced level"],
}

export function ExplanationDocument({ explanation, context, french, onAction, disabled, usedRequests, ownerId, onDiscuss }: {
  explanation: ExplanationV2; context?: DocumentUnitContext; french: boolean
  onAction?: (action: UnitAction, label: string) => void; disabled?: boolean; usedRequests?: ReadonlySet<string>
  ownerId?: string
  onDiscuss?: (question: string) => void
}) {
  const id = useId()
  const model = explanationDocument(explanation, context)
  const source = explanation.course_progress
  const activity = { ownerId, documentId: source?.document_id, generation: source?.index_generation, sourceHash: source?.source_hash }
  const currentVersions = context?.live ? explanationUnits(context.live).map(({ current }) => current) : explanation.versions
  const budget = hasBudgetLimit(context?.live ? currentVersions.map((row) => row.output) : explanation.units)
  const providerCorruption = explanation.units.some(({ interruptions }) =>
    interruptions?.includes("provider_text_corruption") && interruptions.includes("systemic_generation_failure"))
  const { shell, counts, groups, excluded, partial, remaining } = model
  const currentContent = new Set(explanation.units.filter((output) => output.blocks.length > 0).map((output) => output.logical_id))
  const firstOpen = model.included.find((unit) => currentContent.has(unit.id) && unit.corrections?.some((change) => change.severity === "high"))?.id
    ?? model.included.find((unit) => currentContent.has(unit.id))?.id
    ?? model.included.find((unit) => unit.output?.blocks.length)?.id
  const unitId = (unit: string) => `${id}-${encodeURIComponent(unit)}`
  const groupTitle = (label: string) => shell === "course" ? `${french ? "Partie" : "Part"} ${label}` : `${french ? "Exercice" : "Exercise"} ${label}`
  const scopeLabels = [...new Set(groups.flatMap(({ label }) => label ? [groupTitle(label)] : []))]
  const locale = french ? 0 : 1
  const depth = model.depth && Object.hasOwn(depthLabels, model.depth) ? depthLabels[model.depth][locale] : undefined
  const level = model.level && Object.hasOwn(levelLabels, model.level) ? levelLabels[model.level][locale] : undefined
  const deliverables = shell === "lab" ? model.included.filter((unit) => unit.output?.blocks.some((block) => block.kind === "deliverable")) : []
  const checkpointBlocks = shell === "lab" ? model.included.reduce((total, unit) => total +
    (unit.output?.blocks.filter((block) => block.kind === "checkpoint" && block.provenance !== "unverified").length ?? 0), 0) : 0
  const skippedExercises = excluded.filter((unit) => unit.progress?.scope_reason === "exercise_excluded").length
  const actions = model.actions.filter((action) => !usedRequests?.has(action.request_id))
  const deepen = actions.find((action) => action.action === "deepen_unit" && !action.disabled)
    ?? actions.find((action) => action.action === "deepen_unit")
  const next = actions.find((action) => action.action === "continue_learning")
  const nextUnit = next && model.units.get(next.logical_id)
  const availability = [deepen, next].flatMap((action) => action ? [action] : [])
  const title = shell === "exercises" ? (french ? "Série d’exercices" : "Exercise series")
    : shell === "lab" ? (french ? "Feuille de route" : "Lab roadmap")
      : shell === "course" ? (french ? "Plan du cours" : "Course plan") : (french ? "Plan de l’explication" : "Explanation plan")
  const planList = (list: typeof remaining) => <ul className="mt-1 list-disc space-y-1 ps-5">
    {list.map((entry) => <li key={entry.logical_id}><a href={`#${unitId(entry.logical_id)}`} className="underline underline-offset-2">
      {model.units.get(entry.logical_id)?.identity?.label || entry.title}</a></li>)}
  </ul>
  return <div data-explanation-shell={shell} className="min-w-0 space-y-4 px-4 py-3 text-sm sm:px-6 print:px-0">
    {providerCorruption && <p role="status" className="rounded-lg border px-3 py-2">
      {french ? "Le fournisseur a renvoyé du texte corrompu. L’explication concernée n’a pas pu être conservée de manière fiable."
        : "The provider returned corrupted text. The affected explanation could not be safely retained."}
    </p>}
    {(context?.live || context?.turn || budget) && <ExplanationRunStatus turn={context?.live ?? context?.turn}
      french={french} budget={budget}
      remaining={budget && !context?.live && Array.isArray(explanation.coverage_ledger.remaining) ? remaining.length : undefined}
      ready={budget ? currentVersions.filter((row) => row.stage === "ready" && row.output.blocks.length > 0).length : undefined}
      next={next && nextUnit && onAction && !disabled && !next.disabled
        ? { href: `#${id}-actions`, label: documentActionLabel(next, nextUnit, shell, french) } : undefined} />}
    {explanation.historical_source && <p className="rounded-lg border px-3 py-2 text-sm">
      {french ? "La version actuelle du PDF n’a pas pu être confirmée. Cette explication reste consultable dans sa version historique."
        : "The PDF version could not be confirmed as current. This explanation remains available as a historical version."}
    </p>}
    {onAction && availability.length > 0 && <a href={`#${id}-actions`}
      className="inline-flex min-h-11 items-center underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-ring sm:hidden">
      {french ? "Aller aux actions" : "Go to actions"}</a>}
    {(scopeLabels.length > 0 || depth || level || model.assumptions.length > 0 || excluded.length > 0) && <div className="space-y-1.5">
      <div className={controls}>
        <span className="font-medium">{french ? "Périmètre compris" : "Requested scope"}</span>
        {[...scopeLabels, level, depth].filter(Boolean).map((label) => <span key={label} className={chip}>{label}</span>)}
        {excluded.length > 0 && <a href={`#${id}-excluded`} className="text-xs underline underline-offset-2">
          {skippedExercises > 0 ? `${skippedExercises} ${french
            ? (skippedExercises === 1 ? "élément ignoré à votre demande" : "éléments ignorés à votre demande") : "skipped at your request"}`
            : `${excluded.length} ${french ? "hors demande" : "out of scope"}`}</a>}
      </div>
      {model.assumptions.map((assumption, index) => <p key={index} className="text-xs text-muted-foreground" dir="auto">
        {french ? "Hypothèse" : "Assumption"} · {assumption}
      </p>)}
    </div>}
    {(counts || model.checking > 0 || model.lowFidelityPages.length > 0 || checkpointBlocks > 0) && <div
      className={`space-y-2 rounded-lg border p-3 ${counts?.partial ? "border-tertiary/40 bg-tertiary/10" : "bg-muted/30"}`}>
      {counts && <p className="font-semibold" data-coverage-total={counts.total}>{countLabel(shell, french, counts.explained, counts.total)}</p>}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {!!counts?.partial && <span>{counts.partial} {french ? (counts.partial === 1 ? "partiel" : "partiels") : "partial"}</span>}
        {model.checking > 0 && <span>{model.checking} {french ? "en vérification" : "checking"}</span>}
        {!!counts?.notGenerated && <span>{counts.notGenerated} {french ? "à venir" : "not yet generated"}</span>}
        {checkpointBlocks > 0 && <span>{checkpointBlocks} {french
          ? (checkpointBlocks === 1 ? "point de contrôle présenté" : "points de contrôle présentés")
          : (checkpointBlocks === 1 ? "checkpoint described" : "checkpoints described")}</span>}
        {model.lowFidelityPages.length > 0 && <span>{french ? "Sources à vérifier" : "Sources to verify"} · p. {model.lowFidelityPages.join(", ")}</span>}
      </div>
      {counts && <div aria-hidden className="flex gap-0.5">
        {model.included.map((unit) => <span key={unit.id} className={`h-1 min-w-0 flex-1 rounded-full ${
          unit.checking ? "bg-primary/60" : unit.progress?.status === "explained" ? "bg-secondary"
            : unit.progress?.status === "partial" ? "bg-tertiary" : "bg-border"}`} />)}
      </div>}
    </div>}
    {(context?.source?.title || context?.source?.pageCount || partial.length > 0 || remaining.length > 0 || model.results.length > 0 || deliverables.length > 0) &&
      <details data-explanation-plan className="rounded-lg border px-3 py-2" onToggle={syncDisclosure}>
        <summary aria-controls={`${id}-plan`} aria-expanded="false" className="min-h-11 cursor-pointer py-2 font-medium focus-visible:outline-2 focus-visible:outline-ring">
          <span className="sm:hidden">Plan</span><span className="hidden sm:inline">{title}</span>
        </summary>
        <div id={`${id}-plan`} className="mt-2 grid min-w-0 gap-3 sm:grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))]">
          {(context?.source?.title || context?.source?.pageCount) && <div className="min-w-0 text-xs text-muted-foreground">
            {context.source.title && <p className="font-medium [overflow-wrap:anywhere]" dir="auto">{context.source.title}</p>}
            {!!context.source.pageCount && <p>{context.source.pageCount} pages</p>}
          </div>}
          {remaining.length > 0 && <div className="min-w-0 text-xs"><p className="font-medium">{french ? "Reste à étudier" : "Remaining units"}</p>{planList(remaining)}</div>}
          {partial.length > 0 && <div className="min-w-0 text-xs"><p className="font-medium">{french ? "À compléter" : "Needs more explanation"}</p>{planList(partial)}</div>}
          {model.results.length > 0 && <div className="min-w-0 text-xs"><p className="font-medium">{french ? "Résultats obtenus" : "Verified results"}</p>
            <dl className="mt-1 space-y-1">{model.results.map((result) => <div key={result.key} className="flex flex-wrap items-baseline gap-x-2 [overflow-wrap:anywhere]">
              <dt>{result.label}</dt><dd className="font-semibold tabular-nums">{result.value}{result.measure && ` ${result.measure}`}</dd>
              <dd className="text-muted-foreground">{unitVerificationLabel(result.verification, french)}</dd>
            </div>)}</dl>
          </div>}
          {deliverables.length > 0 && <div className="min-w-0 text-xs"><p className="font-medium">{french ? "Livrables demandés" : "Required deliverables"}</p>
            <ul className="mt-1 list-disc ps-5">{deliverables.map((unit) => <li key={unit.id}><a href={`#${unitId(unit.id)}`} className="underline">{referenceOf(unit)}</a></li>)}</ul>
          </div>}
        </div>
      </details>}
    {groups.map((group) => {
      const pages = group.units.flatMap(({ identity, progress }) => progress?.pages ?? (identity ? [identity.start, identity.end] : []))
        .filter((page) => Number.isSafeInteger(page) && page > 0)
      const start = Math.min(...pages)
      const end = Math.max(...pages)
      const range = pages.length ? `p. ${start}${end > start ? `–${end}` : ""}` : undefined
      const coverage = shell === "exercises" && counts
        ? `${group.units.filter((unit) => unit.progress?.status === "explained").length} / ${group.units.length}` : undefined
      return <UnitGroup key={group.key} title={group.label && groupTitle(group.label)} french={french} pages={range} coverage={coverage}
        expandable={group.units.some((unit) => Boolean(unit.output))}>
        {group.units.map((unit) => <UnitRow key={unit.id} id={unitId(unit.id)} unit={unit} model={model} french={french}
          open={unit.id === firstOpen || !!unit.lifecycle || unit.liveCoverage !== undefined}
          historical={explanation.historical_source} activity={activity}
          onDiscuss={disabled ? undefined : onDiscuss} />)}
      </UnitGroup>
    })}
    {model.nonTeaching.map((unit) => unit.output && <ExplanationUnit key={unit.id} output={unit.output}
      identity={unit.identity} progress={unit.progress} documentId={unit.documentId} french={french} />)}
    {excluded.length > 0 && <details id={`${id}-excluded`} className="min-w-0">
      <summary className="cursor-pointer font-medium">{french ? "Hors demande" : "Out of scope"} ({excluded.length})</summary>
      <div className="mt-2 space-y-2">{excluded.map((unit) => <UnitRow key={unit.id} id={unitId(unit.id)}
        unit={unit} model={model} french={french} open={false} />)}</div>
    </details>}
    {!groups.length && !excluded.length && !model.nonTeaching.length &&
      <p className="text-muted-foreground">{french ? "Aucune unité disponible pour cette réponse." : "No units are available for this response."}</p>}
    {onAction && availability.length > 0 && <div id={`${id}-actions`} className={`scroll-mb-4 border-t pt-3 ${controls}`}>
      {availability.map((action) => {
        const unit = model.units.get(action.logical_id)!
        const label = documentActionLabel(action, unit, shell, french)
        return <Button type="button" key={action.request_id} size="sm"
          variant={action.action === "continue_learning" ? "default" : "outline"}
          className="h-auto min-h-11 max-w-full whitespace-normal text-start [overflow-wrap:anywhere] sm:min-h-9"
          disabled={disabled || action.disabled} title={action.disabled_reason} onClick={() => onAction(action, label)}>{label}</Button>
      })}
    </div>}
  </div>
}
