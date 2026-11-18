"use client"

import { PdfCitation } from "@/components/documents/PdfCitation"
import { StudyCode, StudyCopy, StudyMarkdown } from "@/components/notebook/NotebookReply"
import { unitPresentation, type Correction, type UnitBlock, type UnitIdentity, type UnitOutput,
  type UnitProgress } from "@/lib/explanation-v2"
import { lexStudyMarkdown } from "@/lib/notebook/document"
import { requirementActivityId, UnitActivityToggle, unitActivityKey, type UnitActivityScope } from "@/components/chat/UnitActivity"
import type { UnitVersion } from "@/lib/explanation-v2"
import { Button } from "@/components/ui/button"

const blockOrder = {
  concept: ["explanation", "intuition", "source_example", "takeaway", "check_question"],
  derivation: ["given", "ordered_steps", "result", "interpretation"],
  worked_calculation: ["given_values", "formula", "substitution", "calculation", "result", "verification", "interpretation"],
  comparison: ["criteria", "table", "interpretation", "trade_off"],
  figure_walkthrough: ["figure", "what_it_shows", "how_to_read", "specific_reading", "takeaway"],
  rule_examples: ["rule", "sourced_examples", "interpretation", "common_error"],
  exercise: ["problem", "method", "working", "final_answer", "verification"],
  lab_step: ["action", "command_or_ui", "code", "expected_result", "checkpoint", "deliverable", "common_error", "troubleshooting"],
  research_finding: ["evidence", "table", "interpretation", "limitations", "figure"],
  non_teaching: [],
  unknown: [],
}

const labels: Record<string, [string, string]> = {
  intuition: ["Intuition", "Intuition"], source_example: ["Exemple", "Example"],
  takeaway: ["À retenir", "Takeaway"], given: ["Données", "Given"],
  ordered_steps: ["Étapes", "Steps"], result: ["Résultat", "Result"],
  interpretation: ["Interprétation", "Interpretation"], given_values: ["Valeurs données", "Given values"],
  formula: ["Formule", "Formula"], substitution: ["Substitution", "Substitution"],
  calculation: ["Calcul", "Calculation"], criteria: ["Critères", "Criteria"],
  table: ["Tableau", "Table"], trade_off: ["Compromis", "Trade-off"],
  what_it_shows: ["Ce que montre la figure", "What the figure shows"],
  how_to_read: ["Comment lire la figure", "How to read the figure"],
  specific_reading: ["Lecture de la figure", "Reading the figure"],
  figure: ["Figure", "Figure"], rule: ["Règle", "Rule"], sourced_examples: ["Exemples", "Examples"],
  common_error: ["Erreur fréquente", "Common error"], problem: ["Énoncé", "Question"],
  method: ["Méthode", "Method"], working: ["Résolution", "Working"],
  final_answer: ["Réponse finale", "Final answer"], verification: ["Vérification", "Verification"],
  action: ["Action", "Action"], command_or_ui: ["Commande ou étapes", "Command or interface steps"],
  code: ["Code", "Code"], expected_result: ["Résultat attendu", "Expected result"],
  checkpoint: ["Point de contrôle", "Checkpoint"], deliverable: ["Livrable demandé", "Required deliverable"],
  troubleshooting: ["Dépannage", "Troubleshooting"],
  evidence: ["Éléments de preuve", "Evidence"], limitations: ["Limites", "Limitations"],
  check_question: ["Question de vérification", "Check question"],
}

const callout: Record<string, string> = {
  takeaway: "border-secondary/35 bg-secondary/10",
  result: "border-secondary/35 bg-secondary/10",
  final_answer: "border-secondary/35 bg-secondary/10",
  rule: "border-secondary/35 bg-secondary/10",
  common_error: "border-tertiary/40 bg-tertiary/10",
  troubleshooting: "border-tertiary/40 bg-tertiary/10",
  limitations: "border-tertiary/40 bg-tertiary/10",
  interpretation: "border-primary/20 bg-primary/5",
  checkpoint: "border-border bg-muted/40",
  verification: "border-border bg-muted/40",
  problem: "border-border bg-muted/40",
}

const provenance = {
  derived: ["Dérivé de la source", "Derived from source"],
  supplementary: ["Explication Socra, hors du PDF", "Socra explanation, outside the PDF"],
  unverified: ["Non vérifié", "Unverified"],
}

const caption = "text-xs font-semibold text-muted-foreground"
const pill = "inline-flex rounded-md border px-2 py-0.5 text-xs"

function validPage(page: unknown): page is number {
  return typeof page === "number" && Number.isSafeInteger(page) && page > 0
}

function blockSources(block: UnitBlock, output: UnitOutput) {
  if (block.provenance === "supplementary" || block.provenance === "unverified" || !Array.isArray(block.source_indexes)) return []
  return [...new Set(block.source_indexes)].flatMap((index) => {
    const source = Number.isSafeInteger(index) && index > 0 ? output.sources[index - 1] : undefined
    return source && validPage(source.page) && Number.isSafeInteger(source.start) && source.start >= 0 &&
      Number.isSafeInteger(source.end) && source.end > source.start && typeof source.quote === "string" && source.quote.trim()
      ? [source] : []
  })
}

function blockTokens(kind: string, text: string) {
  // Some payloads place LaTeX inside a math code fence. Use the shared display-math tokenizer.
  const fencedMath = kind === "formula" &&
    /^(`{3,}|~{3,})(?:math|latex|tex)?[ \t]*\r?\n([\s\S]+?)\r?\n\1\s*$/i.exec(text.trim())
  const tokens = lexStudyMarkdown(fencedMath ? "$$" + fencedMath[2] + "$$" : text)
  if (kind !== "ordered_steps" && kind !== "how_to_read" && kind !== "working") return tokens
  return tokens.map((token) => token.type === "list" && !token.ordered && !token.items.some((item: { task: boolean }) => item.task)
    ? { ...token, ordered: true, start: 1 } : token)
}

function InstructionalBlock({ block, output, documentId, french, repeated, activity }: {
  block: UnitBlock; output: UnitOutput; documentId?: string; french: boolean; repeated: boolean; activity?: UnitActivityScope
}) {
  const locale = french ? 0 : 1
  const label = !repeated && Object.hasOwn(labels, block.kind) ? labels[block.kind][locale] : undefined
  const variant = Object.hasOwn(callout, block.kind) ? callout[block.kind] : undefined
  const badge = block.provenance === "derived" && block.calculation
    ? (french ? "Dérivé · recalculé" : "Derived · recalculated")
    : block.provenance !== "course" && Object.hasOwn(provenance, block.provenance)
    ? provenance[block.provenance][locale] : undefined
  const sources = blockSources(block, output)
  const hypothetical = block.hypothetical === true && block.provenance === "supplementary"
  const approximate = block.approximate === true
  const lineEnding = block.text.includes("\r\n") ? "\r\n" : block.text.includes("\r") ? "\r" : undefined
  const tokens = blockTokens(block.kind, block.text)
  return <div data-explanation-block={block.kind}
    className={`min-w-0 space-y-2 [&_table]:[overflow-wrap:normal] ${variant ? "rounded-lg border px-3 py-2.5 " + variant : ""}`}>
    {(label || badge || hypothetical || approximate) && <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-muted-foreground">
      {label && <h5 className={caption}>{label}</h5>}
      {badge && <span className={pill}>{badge}</span>}
      {hypothetical && <span className={pill}>{french
        ? "Exemple hypothétique de Socra, pas le calcul du PDF" : "Hypothetical Socra example, outside the PDF calculation"}</span>}
      {approximate && <span className={pill}>{french
        ? "Valeurs lues sur le graphique : approximatives" : "Values read from the chart are approximate"}</span>}
    </div>}
    {block.kind === "code" && !tokens.some((token) => token.type === "code")
      ? <StudyCode value={block.text} language={typeof block.language === "string" ? block.language : undefined} french={french} selectCopyFallback />
      : <StudyMarkdown tokens={tokens} presentation={{ codeLineEnding: lineEnding, french, selectCopyFallback: true }} />}
    {block.kind === "final_answer" && block.provenance !== "unverified" && <div className="print:hidden">
      <StudyCopy value={block.text} label={french ? "Copier la réponse" : "Copy answer"} french={french} selectFallback />
    </div>}
    {sources.length > 0 && <details className="text-xs text-muted-foreground">
      <summary className="cursor-pointer font-medium">{french ? "Sources du bloc" : "Block sources"}</summary>
      <ul className="mt-2 space-y-2">{sources.map((source) => <li key={JSON.stringify([source.page, source.start, source.end, source.quote])}>
        <PdfCitation documentId={documentId} page={source.page} filename="PDF" />
        <p className="[overflow-wrap:anywhere]" dir="auto">{source.quote}</p>
      </li>)}</ul>
    </details>}
    {activity && block.provenance === "course" && sources.length > 0 && !!block.block_id &&
      (block.kind === "checkpoint" || block.kind === "deliverable") &&
      <UnitActivityToggle storageKey={unitActivityKey(activity, output, requirementActivityId(block.block_id, block.text))}
        label={block.kind === "checkpoint" ? (french ? "J’ai effectué ce contrôle" : "I performed this check")
          : (french ? "J’ai produit ce livrable" : "I produced this deliverable")} />}
  </div>
}

export function unitCoverageLabel(coverage: UnitOutput["coverage"] | "skipped" | undefined,
  kind: keyof typeof blockOrder, french: boolean, missingEvidence = false) {
  if (coverage === "explained" && !missingEvidence) {
    if (kind === "exercise") return french ? "✓ Répondu" : "✓ Answered"
    if (kind === "lab_step") return french ? "✓ Expliquée" : "✓ Explained"
    return french ? "✓ Expliqué" : "✓ Explained"
  }
  switch (coverage) {
    case "explained": return undefined // Conflicting evidence: show the source warning without a full-coverage claim.
    case "partial": return french ? "◐ Partiel" : "◐ Partial"
    case "mentioned": return french ? "Mentionné" : "Mentioned"
    case "missing": return french ? "Manquant" : "Missing"
    case "not_generated": return french ? "À venir" : "Not yet generated"
  }
}

export function unitVerificationLabel(verification: UnitOutput["verification"], french: boolean) {
  switch (verification) {
    case "reviewed": return french ? "Relu indépendamment" : "Independently reviewed"
    case "deterministic_only": return french ? "Contrôles automatiques" : "Automatic checks"
    case "review_failed":
    case "unreviewed": return french ? "Non relue" : "Not independently reviewed"
  }
}

const labCheckLabels: Record<string, [string, string]> = {
  python_executable: ["Interpréteur Python", "Python interpreter"],
  driver_executable: ["Interpréteur du pilote", "Driver interpreter"],
  spark_imports: ["Imports Spark", "Spark imports"],
  local_master: ["Mode local", "Local mode"],
  application_name: ["Nom de l’application", "Application name"],
  session_creation: ["Création de la session", "Session creation"],
  warn_logging: ["Journalisation WARN", "WARN logging"],
  runtime_version_command: ["Commande de version", "Version command"],
  complete_execution_order: ["Ordre d’exécution", "Execution order"],
  python_cell_syntax: ["Syntaxe de la cellule Python", "Python cell syntax"],
  separate_blocks: ["Séparation des blocs", "Block separation"],
  runtime_qualification: ["Version relevée à l’exécution", "Runtime version qualification"],
  source_grounding: ["Justification par la source", "Source grounding"],
  control_characters: ["Caractères de contrôle", "Control characters"],
}

function LabVerification({ output, stage, french }: {
  output: UnitOutput; stage?: UnitVersion["stage"]; french: boolean
}) {
  const checks = Object.entries(output.lab_verification?.checks ?? {}).filter(([, value]) => typeof value === "boolean")
  if (!checks.length || !output.blocks.length) return null
  const locale = french ? 0 : 1
  const review = output.independent_review
  const reviewLabel = {
    approved: ["Approuvé", "Approved"], incomplete: ["Relecture incomplète", "Incomplete review"],
    rejected: ["Relecture rejetée", "Review rejected"], unreviewed: ["Non relu", "Not reviewed"],
  }[output.review_state ?? "unreviewed"]?.[locale]
  const evidence = Array.isArray(review?.lab_evidence) ? review.lab_evidence.flatMap((item: unknown) =>
    item && typeof item === "object" && "quote" in item && typeof item.quote === "string" ? [item.quote] : []) : []
  const findings = Array.isArray(review?.findings) ? review.findings.flatMap((item: unknown) =>
    item && typeof item === "object" && "detail" in item && typeof item.detail === "string" ? [item.detail] : []) : []
  const readiness = stage === "ready" ? (french ? "Prêt" : "Ready")
    : stage === "draft" || output.review_state === "incomplete" || output.review_state === "rejected"
      ? (french ? "Brouillon" : "Draft") : undefined
  return <details data-lab-verification className="rounded-lg border px-3 py-2 text-xs">
    <summary className="cursor-pointer font-medium">
      {french ? "Contrôles automatiques" : "Automatic checks"} · {checks.filter(([, passed]) => passed).length}/{checks.length}
      {reviewLabel && ` · ${reviewLabel}`}{readiness && ` · ${readiness}`}
    </summary>
    <ul className="mt-2 space-y-1">{checks.map(([key, passed]) =>
      <li key={key}>{(Object.hasOwn(labCheckLabels, key) ? labCheckLabels[key][locale] : key)}
        {passed ? (french ? " · Réussi" : " · Passed") : (french ? " · Échec" : " · Failed")}</li>)}</ul>
    {typeof review?.pedagogy_score === "number" && <p className="mt-2">
      {french ? "Score pédagogique" : "Pedagogy score"} · {review.pedagogy_score}/3
    </p>}
    {evidence.length > 0 && <div className="mt-2">
      <p>{french ? "Éléments de preuve de la relecture" : "Review evidence"} ({evidence.length})</p>
      <ul className="list-disc ps-5">{evidence.map((quote, index) => <li key={index} dir="auto">{quote}</li>)}</ul>
    </div>}
    {findings.length > 0 && <ul className="mt-2 list-disc ps-5" aria-label={french ? "Constats" : "Findings"}>
      {findings.map((detail, index) => <li key={index} dir="auto">{detail}</li>)}
    </ul>}
  </details>
}

export function ExplanationUnit({ output, identity, progress, documentId, historical, french, corrections = [], embedded,
  provisional, activity, history = [], lifecycle, stage, onDiscuss }: {
  output: UnitOutput; identity?: UnitIdentity; progress?: UnitProgress; documentId?: string; historical?: boolean; french: boolean
  corrections?: Correction[]
  embedded?: boolean
  provisional?: boolean
  lifecycle?: string
  stage?: UnitVersion["stage"]
  activity?: UnitActivityScope
  history?: UnitVersion[]
  onDiscuss?: (question: string) => void
}) {
  const kind = unitPresentation(identity?.kind)
  const order: readonly string[] = blockOrder[kind]
  const rank = (block: UnitBlock) => {
    const index = order.indexOf(block.kind)
    return index === -1 ? order.length : index
  }
  const blocks = output.blocks.filter((block) => typeof block?.text === "string" && block.text.trim())
  const checkQuestion = blocks.find((block) => block.kind === "check_question" && block.provenance !== "unverified")?.text
  // Keep packet/subquestion order when a block kind repeats. Otherwise use the instructional sequence.
  if (new Set(blocks.map((block) => block.kind)).size === blocks.length) blocks.sort((a, b) => rank(a) - rank(b))
  const heading = <span className="min-w-0 font-semibold [overflow-wrap:anywhere]" dir="auto">
    {identity?.label && <span className="me-2 text-xs font-medium text-muted-foreground">{identity.label}</span>}{output.title}
  </span>
  const sourceGaps = [...output.unverifiable_source, ...(progress?.unverifiable_source ?? [])]
  const gapPages = [...new Set(sourceGaps.flatMap((gap) => validPage(gap?.page) ? [gap.page] : []))]
  const gapLabels = [...new Set(sourceGaps.flatMap((gap) => {
    const label = french ? gap?.label : gap?.label_en ?? gap?.label
    return typeof label === "string" && label.trim() ? [label] : []
  }))]
  const hasGap = output.unverifiable_source.length > 0 || Boolean(progress?.unverifiable_source.length)
  const missing = new Set([...output.missing_item_ids, ...(progress?.missing_item_ids ?? [])]).size
  const status = unitCoverageLabel(output.coverage, kind, french, hasGap || missing > 0)
  const verification = unitVerificationLabel(output.verification, french)
  const start = identity?.start ?? progress?.pages[0]
  const end = identity?.end ?? progress?.pages[1]
  const figurePage = kind === "figure_walkthrough"
    ? blocks.flatMap((block) => blockSources(block, output))[0]?.page ?? (start === end ? start : undefined)
    : undefined
  const missingDescriptions = [progress?.missing_items, output.missing_items].flatMap((items) =>
    Array.isArray(items) ? items.flatMap((item) => typeof item?.text === "string" && item.text.trim() ? [item.text] : []) : [])
  const body = blocks.map((block, index) => <InstructionalBlock key={block.block_id} block={block} output={output}
    documentId={documentId} french={french} repeated={blocks[index - 1]?.kind === block.kind}
    activity={!historical && !provisional && kind === "lab_step" && blocks.filter((item) => item.block_id === block.block_id).length === 1
      ? activity : undefined} />)
  if (kind === "non_teaching" || progress?.scope_reason === "non_teaching") {
    return <div data-explanation-unit="non_teaching" className="border-b border-dashed py-2 text-sm text-muted-foreground">
      {identity?.kind === "summary" && body.length ? <details><summary className="cursor-pointer">{heading}</summary>
        <div className="mt-3 space-y-3">{body}</div></details> : heading}
    </div>
  }
  return <section data-explanation-unit={kind} className={`min-w-0 space-y-3 px-3 py-3 text-sm sm:px-4 ${embedded ? "" : "rounded-xl border"}`}>
    {!embedded && <header className="flex flex-wrap items-baseline justify-between gap-2">
      <h4>{heading}</h4>
      <div className="flex flex-wrap gap-1.5 text-muted-foreground">
        {validPage(start) && <span className={pill}>p. {start}{validPage(end) && end > start ? `–${end}` : ""}</span>}
        {historical ? <span className={pill}>{french ? "À régénérer" : "Historical version"}</span>
          : !provisional && status && <span className={pill}>{status}</span>}
        {provisional && <span className={pill}>{french ? "Provisoire" : "Provisional"}</span>}
        {lifecycle && <span className={pill}>{lifecycle}</span>}
      </div>
    </header>}
    {kind === "lab_step" && <LabVerification output={output} stage={stage} french={french} />}
    {validPage(figurePage) && <div className="text-xs"><PdfCitation documentId={documentId} page={figurePage} filename="PDF" /></div>}
    {(hasGap || missing > 0) && <aside className="space-y-1 rounded-lg border border-tertiary/40 bg-tertiary/10 px-3 py-2 text-xs">
      {hasGap && <p>{french ? "Source non vérifiable" : "Unverifiable source"}
        {gapPages.length > 0 && ` · p. ${gapPages.join(", ")}`}</p>}
      {gapLabels.length > 0 && <ul className="list-disc ps-5">{gapLabels.map(label =>
        <li key={label} dir="auto">{label}</li>)}</ul>}
      {missing > 0 && <p>{french ? `Éléments manquants (${missing})` : `Missing requirements (${missing})`}</p>}
      {missingDescriptions.length > 0 && <ul className="list-disc ps-5">{[...new Set(missingDescriptions)].map((text) =>
        <li key={text} dir="auto">{text}</li>)}</ul>}
    </aside>}
    {corrections.length > 0 && <details open={corrections.some((change) => change.severity === "high") || undefined}
      className="rounded-lg border border-tertiary/40 bg-tertiary/10 px-3 py-2 text-xs">
      <summary className="min-h-11 cursor-pointer py-2 font-medium">{french ? "Contenu corrigé" : "Content corrected"}</summary>
      <ul className="space-y-3">{corrections.map(({ block_id, old_quote, new_quote, severity, reason }, index) => {
        const block = blocks.find((item) => item.block_id === block_id)
        const pages = [...new Set(block ? blockSources(block, output).map((source) => source.page) : [])]
        return <li key={JSON.stringify([block_id, old_quote, new_quote, index])} className="space-y-1 [overflow-wrap:anywhere]">
          {severity && <p>{french ? "Gravité" : "Severity"} · {french
            ? ({ high: "haute", medium: "moyenne", low: "faible" } as Record<string, string>)[severity] ?? severity : severity}</p>}
          {reason && <p>{french ? "Motif" : "Reason"} · {reason === "review_repair"
            ? (french ? "Correction après relecture" : "Revision after review") : reason}</p>}
          {old_quote && <p>{french ? "Avant" : "Before"} · <del>{old_quote}</del></p>}
          {new_quote && <p>{french ? "Après" : "After"} · <ins className="bg-secondary/15">{new_quote}</ins></p>}
          {pages.map((page) => <PdfCitation key={page} documentId={documentId} page={page} filename="PDF" />)}
        </li>
      })}</ul>
    </details>}
    {body.length > 0 && <div className="min-w-0 space-y-3 leading-relaxed">{body}</div>}
    {!provisional && verification && (body.length > 0 || output.verification !== "unreviewed") && <footer className="flex flex-wrap items-center gap-2 text-muted-foreground">
      <span className={pill}>{verification}</span>
      {output.verification === "review_failed" && output.confidence && <span className={pill}>{french ? "Confiance" : "Confidence"} · {french
        ? { low: "faible", medium: "moyenne", high: "haute" }[output.confidence] : output.confidence}</span>}
      {!historical && body.length > 0 && <UnitActivityToggle storageKey={unitActivityKey(activity, output, "read")}
        label={french ? "Marquer comme relu" : "Mark as reread"} />}
      {!historical && checkQuestion && onDiscuss && <Button type="button" variant="ghost" className="min-h-11" size="sm"
        onClick={() => onDiscuss(checkQuestion)}>{french ? "Dialogue socratique" : "Socratic dialogue"}</Button>}
    </footer>}
    {history.length > 0 && <details className="rounded-lg border px-3 text-sm">
      <summary className="min-h-11 cursor-pointer py-2 font-medium">{french ? "Historique des versions" : "Version history"} ({history.length})</summary>
      {history.map((row, index) => <details key={JSON.stringify([row.request_id, row.stage, row.generation, row.output.content_version])} className="border-t">
        <summary className="min-h-11 cursor-pointer py-2">{french ? "Version antérieure" : "Earlier version"} {index + 1}
          {row.stage !== "ready" && (french ? " · Provisoire" : " · Provisional")}</summary>
        <ExplanationUnit output={row.output} identity={row.identity}
          documentId={!historical && row.document_id === documentId &&
            (!activity || (row.generation === activity.generation && row.source_hash === activity.sourceHash))
            ? documentId : undefined} french={french}
          embedded historical provisional={row.stage !== "ready"} corrections={row.change_log} />
      </details>)}
    </details>}
  </section>
}

