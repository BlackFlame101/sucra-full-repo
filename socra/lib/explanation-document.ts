import { explanationUnits, supportedUnitActions, unitPresentation, type Correction, type ExplanationV2, type UnitAction,
  type UnitIdentity, type UnitOutput, type UnitProgress, type UnitVersion, type ExplanationTurn } from "@/lib/explanation-v2"

export type DocumentShell = "course" | "exercises" | "lab" | "neutral"

export interface DocumentUnit {
  id: string
  identity?: UnitIdentity
  progress?: UnitProgress
  output?: UnitOutput
  corrections?: Correction[]
  documentId?: string
  excluded: boolean
  nonTeaching: boolean
  checking: boolean
  provisional?: boolean
  stage?: UnitVersion["stage"]
  provisionalVersion?: UnitVersion
  liveCoverage?: UnitOutput["coverage"]
  lifecycle?: string
  stale?: boolean
  history: UnitVersion[]
  dependencies: string[]
}

export interface DocumentUnitContext {
  previous?: UnitVersion[]
  checking?: UnitVersion[]
  turn?: ExplanationTurn
  live?: ExplanationTurn
  source?: { title?: string; pageCount?: number }
}

type UnitWithVersion = Pick<UnitOutput, "logical_id" | "content_version">

const unitKey = (unit: UnitWithVersion) => JSON.stringify([unit.logical_id, unit.content_version])

function matchesSource(row: UnitVersion, document: ExplanationV2["course_progress"]) {
  return !!document?.document_id && !!document.source_hash && document.index_generation !== undefined
    && row.document_id === document.document_id && row.generation === document.index_generation
    && row.source_hash === document.source_hash
}

function dominantShell(units: DocumentUnit[]): DocumentShell {
  if (!units.some((unit) => unit.progress)) return "neutral"
  const candidates = units.filter((unit) => !unit.nonTeaching)
  const totals = { course: 0, exercises: 0, lab: 0 }
  for (const unit of candidates) {
    const identity = unit.identity
    const kind = unitPresentation(identity?.kind)
    if (identity?.fallback === true) continue
    if (kind === "exercise" || unit.progress?.scope_reason === "exercise_excluded") totals.exercises++
    else if (kind === "lab_step") totals.lab++
    else if (kind !== "unknown" && kind !== "research_finding") totals.course++
  }
  const majority = (Object.keys(totals) as Array<keyof typeof totals>).find((kind) => totals[kind] > candidates.length / 2)
  if (majority) return majority
  // A complete map can identify a TP with both teaching notes and follow-up exercises.
  if (totals.course + totals.exercises + totals.lab === candidates.length &&
      totals.lab > totals.course && totals.lab > totals.exercises) return "lab"
  return "neutral"
}

function groupLabel(unit: DocumentUnit, shell: DocumentShell) {
  const path = unit.identity?.heading_path
  if (Array.isArray(path)) {
    for (const component of path) {
      const label = Array.isArray(component) && typeof component[0] === "string" ? component[0] : ""
      if (shell === "course" && /^[IVXLCDM]+$/i.test(label)) return label.toUpperCase()
      if (shell === "exercises") {
        const exercise = /^(?:exerci(?:ce|se)\s+)(\d+)$/i.exec(label)?.[1]
        if (exercise) return exercise
      }
    }
  }
  const label = unit.identity?.label?.trim()
  if (!label) return
  if (shell === "course") return /^([IVXLCDM]+)\.\d/i.exec(label)?.[1].toUpperCase()
  if (shell === "exercises") return /^(?:exerci(?:ce|se)\s+)(\d+)(?:\b|$)/i.exec(label)?.[1]
    ?? /^(\d+)\.[a-z\d]+(?:\b|$)/i.exec(label)?.[1]
}

function groupUnits(units: DocumentUnit[], shell: DocumentShell) {
  // Keep contiguous runs so grouping never changes prerequisite ordering.
  const numbered = new Set(units.flatMap((unit) => {
    const label = /^(?:exerci(?:ce|se)\s+)(\d+)/i.exec(unit.identity?.label ?? "")?.[1]
    return label ? [label] : []
  }))
  const groups: Array<{ key: string; label?: string; units: DocumentUnit[] }> = []
  for (const unit of units) {
    const guessed = groupLabel(unit, shell)
    const explicit = Array.isArray(unit.identity?.heading_path)
    const label = shell !== "exercises" || explicit || numbered.has(guessed ?? "") ? guessed : undefined
    const last = groups.at(-1)
    if (last && last.label === label) last.units.push(unit)
    else groups.push({ key: unit.id, label, units: [unit] })
  }
  return groups
}

function verifiedResults(explanation: ExplanationV2, units: DocumentUnit[]) {
  const allowed = new Map(units.filter((unit) => !unit.excluded && !unit.nonTeaching).map((unit) => [unit.id, unit]))
  return (explanation.learning_state.facts?.verified_facts ?? []).flatMap((fact, index) => {
    if (typeof fact?.unit_id !== "string" || (typeof fact.value !== "string" && typeof fact.value !== "number")
        || (fact.verification !== "reviewed" && fact.verification !== "deterministic_only")
        || (Array.isArray(fact.authoritative_errors) && fact.authoritative_errors.length > 0)) return []
    const unit = allowed.get(fact.unit_id)
    if (!unit || unit.progress?.status !== "explained" || fact.content_version !== unit.progress.content_version) return []
    const label = unit.identity?.label || unit.progress.title
    return [{ key: `${unit.id}-${index}`, unitId: unit.id, label, value: String(fact.value), verification: fact.verification,
      measure: typeof fact.unit === "string" ? fact.unit : undefined } as const]
  })
}

export function explanationDocument(explanation: ExplanationV2, context: DocumentUnitContext = {}) {
  const doc = explanation.course_progress
  const plan = doc?.learning_plan
  const versions = new Map<string, UnitVersion>()
  const previous = new Map<string, UnitVersion>()
  if (!explanation.historical_source) {
    for (const row of context.previous ?? []) {
      if (row.stage === "ready" && row.output.blocks.length && matchesSource(row, doc)) previous.set(unitKey(row.output), row)
    }
  }
  for (const row of explanation.versions) {
    if (row.stage === "ready") versions.set(unitKey(row.output), row)
  }
  const live = new Map((!explanation.historical_source && context.live ? explanationUnits(context.live) : [])
    .filter(({ current }) => matchesSource(current, doc)).map((unit) => [unitKey(unit.current.output), unit]))
  const saved = new Map((context.turn ? explanationUnits(context.turn) : [])
    .map((unit) => [unitKey(unit.current.output), unit]))
  const allVersions = [...(context.previous ?? []), ...(context.turn?.stream.versions ?? explanation.versions)]
  const checking = new Set((explanation.historical_source ? [] : context.checking ?? [])
    .filter((row) => matchesSource(row, doc)).map((row) => unitKey(row.output)))
  const identities = new Map((doc?.sections ?? []).map((row) => [unitKey({ logical_id: row.id, content_version: row.content_version }), row]))
  const outputs = new Map(explanation.units.map((row) => [unitKey(row), row]))
  const progress = new Map(explanation.learning_state.progress.map((row) => [unitKey(row), row]))
  const units = new Map<string, DocumentUnit>()
  for (const key of new Set([...progress.keys(), ...outputs.keys()])) {
    const row = progress.get(key)
    const owned = outputs.get(key)
    const reusable = row && (row.status === "explained" || row.status === "partial" || row.status === "mentioned")
      ? previous.get(key) : undefined
    const archived = !owned?.blocks.length ? reusable : undefined
    const liveUnit = live.get(key)
    const ownVersion = archived ?? versions.get(key)
    // The existing ready content stays visible during Deepen, including on interruption.
    const keepReady = !!(archived?.output ?? owned ?? ownVersion?.output)?.blocks.length
      && (liveUnit?.current.stage !== "ready" || !liveUnit.current.output.blocks.length)
    const showLive = !keepReady && !!liveUnit
    const version = showLive ? liveUnit.current : ownVersion
    const source = showLive ? version?.output : archived?.output ?? owned ?? version?.output
    if (!row && !source) continue
    const id = row?.logical_id ?? source!.logical_id
    const reason = row?.scope_reason ?? plan?.scope?.[id]?.reason
    const excluded = row?.status === "skipped" || plan?.scope?.[id]?.in_scope === false
    const identity = version?.identity ?? identities.get(key) ?? (row?.kind ? {
      id, kind: row.kind, label: row.label ?? undefined, title: row.title,
      start: row.pages[0], end: row.pages[1], content_version: row.content_version, fallback: row.fallback,
    } : undefined)
    const nonTeaching = reason === "non_teaching" || unitPresentation(identity?.kind) === "non_teaching"
    const deps = identity?.depends_on ?? row?.depends_on
    const invalidated = doc?.unit_reconciliation?.find((item) => item.stale && item.current_ids.includes(id))
    const stale = Boolean(explanation.historical_source || (!source?.blocks.length && (identity?.stale === true || invalidated)))
    const history = new Map<string, UnitVersion>()
    for (const entry of [...allVersions, ...liveUnit?.versions ?? []]) {
      const sameSource = matchesSource(entry, doc)
      const reconciled = invalidated && entry.output.logical_id === invalidated.prior_id && entry.document_id === doc?.document_id
      if ((!sameSource || unitKey(entry.output) !== key) && !reconciled) continue
      if (entry.request_id === version?.request_id && entry.stage === version.stage &&
        entry.generation === version.generation && entry.output.content_version === version.output.content_version) continue
      if (!entry.output.blocks.length) continue
      history.set(JSON.stringify([entry.request_id, entry.stage, entry.generation, entry.output.content_version]), entry)
    }
    units.set(id, { id, identity, progress: row, output: !excluded || nonTeaching ? source : undefined,
      documentId: version?.document_id ?? doc?.document_id,
      corrections: showLive ? liveUnit.corrections : saved.get(key)?.corrections ?? version?.change_log,
      excluded, nonTeaching, checking: !excluded && (checking.has(key) || liveUnit?.lifecycle === "checking"),
      provisional: version?.stage === "draft" || version?.stage === "repaired", stage: version?.stage,
      lifecycle: liveUnit?.lifecycle, stale,
      provisionalVersion: keepReady && liveUnit?.current.stage !== "ready" ? liveUnit?.current : undefined,
      liveCoverage: liveUnit?.current.stage === "ready" ? liveUnit.current.output.coverage : undefined,
      history: [...history.values()].reverse(),
      dependencies: Array.isArray(deps) ? deps.filter((item): item is string => typeof item === "string" && item !== id) : [] })
  }
  const all = [...units.values()]
  const shell = dominantShell(all)
  const ordered = new Set([...(plan?.order ?? []), ...units.keys()])
  const included = [...ordered].flatMap((id) => {
    const unit = units.get(id)
    return unit && !unit.excluded && !unit.nonTeaching ? [unit] : []
  })
  const groups = groupUnits(included, shell)
  const excluded = all.filter((unit) => unit.excluded && !unit.nonTeaching)
  const counts = explanation.coverage_ledger.coverage_counts
  // Phase 7's ledger covers the full Unit Map. Verify that each eligible status
  // agrees before announcing a total, excluding skipped and non-teaching rows.
  const countsAgree = !explanation.historical_source && included.length > 0
    && included.every((unit) => unit.progress && !(unit.stale && unit.progress.status === "explained"))
    && (["explained", "partial", "mentioned", "missing", "not_generated"] as const).every((status) =>
      (counts?.[status] ?? 0) === included.filter((unit) => unit.progress?.status === status).length)
    && included.every((unit) => ["explained", "partial", "mentioned", "missing", "not_generated"].includes(unit.progress?.status ?? ""))
    && (!plan?.scope || Object.entries(plan.scope).every(([id, scope]) => !scope.in_scope || units.has(id)))
  const actionRows = supportedUnitActions(explanation).filter((action) => {
    if (!action.request_id || !action.logical_id) return false
    const row = units.get(action.logical_id)
    if (!row || row.excluded || row.nonTeaching || row.stale) return false
    if (action.action === "continue_learning") return row.progress?.status === "not_generated"
    return row.progress?.status === "partial" || row.progress?.status === "mentioned" || row.progress?.status === "missing"
  })
  return {
    shell, units, groups, included, excluded,
    nonTeaching: all.filter((unit) => unit.nonTeaching && unit.output),
    counts: countsAgree ? { total: included.length, explained: counts.explained ?? 0, partial: counts.partial ?? 0,
      notGenerated: counts.not_generated ?? 0 } : undefined,
    partial: (explanation.coverage_ledger.partial ?? []).filter((unit) => included.some(({ id }) => id === unit.logical_id)),
    remaining: (explanation.coverage_ledger.remaining ?? []).filter((unit) => included.some(({ id }) => id === unit.logical_id)),
    checking: included.filter((unit) => unit.checking).length,
    lowFidelityPages: [...new Set((explanation.coverage_ledger.low_fidelity_pages ?? [])
      .filter((page) => Number.isSafeInteger(page) && page > 0))],
    results: shell === "exercises" ? verifiedResults(explanation, all) : [],
    assumptions: plan?.assumptions ?? [],
    level: plan?.level,
    depth: plan?.depth,
    actions: actionRows,
  }
}

export function documentActionLabel(action: UnitAction, unit: DocumentUnit, shell: DocumentShell, french: boolean) {
  const reference = unit.identity?.label || unit.progress?.title || unit.output?.title || action.label
  if (action.action === "continue_learning") {
    const title = unit.progress?.title ?? unit.output?.title
    const target = shell === "course" && title && reference && title !== reference ? `${reference} ${title}` : reference
    return [french ? "Continuer" : "Continue", target].filter(Boolean).join(" : ")
  }
  const verb = shell === "course" || shell === "neutral" ? (french ? "Approfondir" : "Deepen")
    : (french ? "Compléter" : "Complete")
  return [verb, reference].filter(Boolean).join(" ")
}
