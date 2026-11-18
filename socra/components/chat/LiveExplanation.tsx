"use client"

import { ExplanationUnit } from "@/components/chat/ExplanationUnit"
import { explanationUnits, unitGenerationInterrupted, type ExplanationTurn, type UnitOutput } from "@/lib/explanation-v2"

export function lifecycleText(lifecycle: string | undefined, french: boolean) {
  switch (lifecycle) {
    case "drafting": return french ? "Génération" : "Generating"
    case "checking": return french ? "Vérification" : "Checking"
    case "corrected": return french ? "Corrigé" : "Corrected"
    case "interrupted": return french ? "Génération interrompue" : "Generation interrupted"
    case "failed": return french ? "Échec de la génération" : "Generation failed"
  }
}

export function hasBudgetLimit(outputs: UnitOutput[]) {
  return outputs.some((output) => output.interruptions?.some((reason) => reason === "call_budget" || reason === "token_budget"))
}

export function ExplanationRunStatus({ turn, french, budget, remaining, ready, next }: {
  turn?: ExplanationTurn; french: boolean; budget?: boolean; remaining?: number; ready?: number
  next?: { href: string; label: string }
}) {
  const units = turn ? explanationUnits(turn) : []
  const preparation = turn?.stream.preparation?.status
  const stopped = turn?.stream.interrupted || turn?.stream.failed || turn?.saved?.units.some(unitGenerationInterrupted)
  const text = preparation === "ready" ? (french ? "Sources prêtes" : "Source evidence ready")
    : preparation === "pending" ? (french ? "Préparation des sources encore incomplète" : "Source preparation is still incomplete")
      : preparation === "loading" ? stopped
        ? (french ? "Préparation des sources non confirmée" : "Source preparation could not be confirmed")
        : (french ? "Préparation des sources" : "Preparing source evidence")
        : null
  const finished = units.filter(({ current }) => current.stage === "ready").length
  const checked = units.filter(({ current }) => current.stage === "ready" && turn?.stream.checking.some((unit) =>
    unit.logical_id === current.output.logical_id && unit.content_version === current.output.content_version)).length
  const corrected = units.reduce((count, unit) => count + unit.corrections.length, 0)
  const active = stopped || turn?.saved ? undefined : units.some(({ lifecycle }) => lifecycle === "checking") ? "checking"
    : units.some(({ lifecycle }) => lifecycle === "drafting") ? "drafting" : undefined
  const announcement = active === "checking" ? (french ? "Vérification du contenu." : "Checking explanation content.")
    : active === "drafting" ? (french ? "Génération du contenu." : "Generating explanation content.")
    : checked > 0 ? (french ? `Vérification terminée pour ${checked} unité(s).` : `Checking finished for ${checked} unit(s).`)
    : finished > 0 ? (french ? `${finished} unité(s) disponible(s).` : `${finished} unit result(s) available.`) : ""
  return <div className="space-y-2 text-sm">
    {text && <p className="text-muted-foreground">{text}</p>}
    {stopped && <p>{turn?.stream.failed
      ? (french ? "La génération s’est arrêtée avant la fin." : "Generation stopped before completion.")
      : (french ? "Génération interrompue." : "Generation interrupted.")}</p>}
    {budget && <aside className="rounded-lg border border-tertiary/40 bg-tertiary/10 px-3 py-2">
      <p className="font-medium">{french ? "Limite de génération atteinte" : "Generation budget reached"}</p>
      {ready !== undefined && <p>{french ? "Unités enregistrées disponibles" : "Saved units available"} · {ready}</p>}
      {remaining !== undefined && <p>{french ? "Unités restantes" : "Remaining units"} · {remaining}</p>}
      {next && <a className="inline-flex min-h-11 items-center underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-ring"
        href={next.href}>{next.label}</a>}
    </aside>}
    <div role="status" aria-atomic="true" className="sr-only">{announcement}</div>
    <div role="status" aria-atomic="true" className="sr-only">
      {corrected > 0 && (french ? `${corrected} correction(s) apportée(s).` : `${corrected} correction(s) made.`)}
    </div>
  </div>
}

export function LiveExplanation({ turn, french }: { turn: ExplanationTurn; french: boolean }) {
  const units = explanationUnits(turn)
  return <section aria-label={french ? "Explication en cours" : "Explanation in progress"}
    className="min-w-0 space-y-3 rounded-xl border bg-card p-3 sm:p-4">
    <ExplanationRunStatus turn={turn} french={french} budget={hasBudgetLimit(units.map(({ current }) => current.output))}
      ready={units.filter(({ current }) => current.stage === "ready" && current.output.blocks.length).length} />
    {units.map(({ current, versions, lifecycle, corrections }) =>
      <ExplanationUnit key={JSON.stringify([current.document_id, current.output.logical_id])} output={current.output}
        identity={current.identity} documentId={current.document_id} french={french} provisional={current.stage !== "ready"}
        stage={current.stage}
        lifecycle={lifecycleText(lifecycle, french)} corrections={corrections}
        history={current.stage === "ready" ? versions.filter((row) => row !== current && row.output.blocks.length > 0) : undefined} />)}
  </section>
}
