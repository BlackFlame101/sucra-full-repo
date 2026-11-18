import type { UIMessage } from "ai"

type Extra = Record<string, unknown>

export type Coverage = "explained" | "partial" | "mentioned" | "missing" | "not_generated"
export type Verification = "unreviewed" | "deterministic_only" | "reviewed" | "review_failed"

export interface UnitIdentity extends Extra {
  id: string
  title: string
  label?: string
  kind?: string
  start: number
  end: number
  content_version: string
}

export function unitPresentation(kind?: string) {
  switch (kind) {
    case "concept":
    case "derivation":
    case "worked_calculation":
    case "comparison":
    case "figure_walkthrough":
    case "rule_examples":
    case "exercise":
    case "lab_step":
    case "research_finding": return kind
    case "front_matter":
    case "transition":
    case "summary":
    case "non_teaching": return "non_teaching"
    default: return "unknown"
  }
}

export interface UnitBlock extends Extra {
  block_id: string
  kind: string
  text: string
  provenance: "course" | "derived" | "supplementary" | "unverified"
  hypothetical?: boolean
  source_indexes: number[] // One-based indexes into this output's sources.
  claims?: Array<{ sentence: string; source_indexes: number[] }>
}

export interface SourceGap extends Extra {
  page?: number
  reason?: string
  status?: string
  label?: string
  label_en?: string
}

export interface UnitOutput extends Extra {
  logical_id: string
  title: string
  content_version: string
  coverage: Coverage
  verification: Verification
  confidence?: "low" | "medium" | "high"
  blocks: UnitBlock[]
  sources: Array<{ page: number; start: number; end: number; quote: string }>
  missing_item_ids: string[]
  unverifiable_source: SourceGap[]
  verified_facts: Extra[]
  findings?: Extra[]
  independent_review?: Extra
  lab_verification?: { checks: Record<string, boolean>; original_item_ids?: string[] }
  review_state?: "unreviewed" | "incomplete" | "rejected" | "approved"
  interruptions?: string[]
}

export interface Correction extends Extra {
  block_id?: string
  old_quote?: string | null
  new_quote?: string | null
  reason?: string
  severity?: string
}

export interface UnitVersion extends Extra {
  request_id: string
  stage: "draft" | "repaired" | "ready"
  output: UnitOutput
  change_log?: Correction[]
  document_id?: string
  generation?: number
  source_hash?: string
  identity?: UnitIdentity
  required_item_ids?: string[]
  replayed?: boolean
}

export interface UnitProgress extends Extra {
  logical_id: string
  title: string
  content_version: string
  pages: [number, number]
  status: Coverage | "skipped"
  verification: Verification | "not_applicable"
  missing_item_ids: string[]
  unverifiable_source: SourceGap[]
  scope_reason?: string
  kind?: string | null
  label?: string | null
  fallback?: boolean | null
}

export interface UnitAction extends Extra {
  action: string
  logical_id: string
  request_id: string
  attempt?: number
  label?: string
  disabled?: boolean
  disabled_reason?: string
}

export interface LearningPlan extends Extra {
  order: string[]
  scope: Record<string, { in_scope: boolean; reason: string }>
  assumptions: string[]
  depth: string
  level: string
  required_items: Record<string, string[]>
  unverifiable_source: Record<string, SourceGap[]>
  remaining: Array<Pick<UnitProgress, "logical_id" | "title" | "pages">>
  next_actions: UnitAction[]
  facts_ledger: Extra[]
}

interface UnitReconciliation extends Extra {
  prior_id: string
  current_ids: string[]
  reason: string
  stale: boolean
}

export interface ExplanationV2 extends Extra {
  schema_version: 2
  units: UnitOutput[]
  versions: UnitVersion[]
  course_progress?: {
    document_id?: string
    index_generation?: number
    source_hash?: string
    sections: UnitIdentity[]
    learning_plan?: LearningPlan
    unit_map_version?: string
    unit_reconciliation?: UnitReconciliation[]
  }
  learning_state: {
    progress: UnitProgress[]
    facts: { verified_facts: Extra[] }
    next_actions: UnitAction[]
  }
  coverage_ledger: {
    coverage_counts: Record<string, number>
    verification_counts: Record<string, number>
    remaining: UnitProgress[]
    partial: UnitProgress[]
    skipped_optional_items: Record<string, string[]>
    low_fidelity_pages: number[]
    corrections: Array<Correction & { logical_id: string }>
    next_actions: UnitAction[]
  }
  historical_source?: boolean
}

type UnitReference = { logical_id: string; content_version: string }
type Preparation = { document_id: string; status: "loading" | "ready" | "pending" }
type CorrectionEvent = Correction & UnitReference & { version_request_id?: string; generation?: number }
export type ExplanationEvent =
  | { type: "prep_status"; content: Preparation }
  | { type: "unit_draft" | "unit_ready"; content: UnitVersion }
  | { type: "unit_checking"; content: UnitReference }
  | { type: "unit_correction"; content: CorrectionEvent }

function record(value: unknown): value is Extra {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function reference(value: unknown): value is UnitReference & Extra {
  return record(value) && typeof value.logical_id === "string" && typeof value.content_version === "string"
}

function output(value: unknown): value is UnitOutput {
  return reference(value) && typeof value.title === "string" && typeof value.coverage === "string"
    && typeof value.verification === "string" && Array.isArray(value.blocks) && Array.isArray(value.sources)
    && Array.isArray(value.missing_item_ids) && Array.isArray(value.unverifiable_source)
    && Array.isArray(value.verified_facts)
}

function version(value: unknown): value is UnitVersion {
  return record(value) && typeof value.request_id === "string" && output(value.output)
    && (value.stage === "draft" || value.stage === "repaired" || value.stage === "ready")
    && (value.change_log === undefined || Array.isArray(value.change_log))
}

function progressRow(value: unknown): value is UnitProgress {
  return reference(value) && typeof value.title === "string" && typeof value.status === "string"
    && typeof value.verification === "string" && Array.isArray(value.pages) && value.pages.length === 2
    && value.pages.every((page) => Number.isInteger(page))
    && Array.isArray(value.missing_item_ids) && Array.isArray(value.unverifiable_source)
}

export function explanationV2(value: unknown): ExplanationV2 | undefined {
  if (record(value) && value.schema_version === 2 && Array.isArray(value.units) && value.units.every(output)
      && Array.isArray(value.versions) && value.versions.every(version)
      && record(value.learning_state) && Array.isArray(value.learning_state.progress)
      && value.learning_state.progress.every(progressRow)
      && Array.isArray(value.learning_state.next_actions) && record(value.coverage_ledger)) {
    return value as ExplanationV2
  }
}

export function isExplanationEventType(type: string): type is ExplanationEvent["type"] {
  return type === "prep_status" || type === "unit_draft" || type === "unit_checking"
    || type === "unit_ready" || type === "unit_correction"
}

export function validExplanationEvent(type: ExplanationEvent["type"], value: unknown) {
  switch (type) {
    case "unit_draft": return version(value) && value.stage !== "ready"
    case "unit_ready": return version(value) && value.stage === "ready"
    case "unit_checking":
    case "unit_correction": return reference(value)
    case "prep_status": return record(value) && typeof value.document_id === "string"
      && (value.status === "loading" || value.status === "ready" || value.status === "pending")
  }
}

export interface ExplanationStream {
  preparation?: Preparation
  preparationSequence?: number
  versions: UnitVersion[]
  checking: UnitReference[]
  corrections: CorrectionEvent[]
  interrupted?: boolean
  failed?: boolean
}

const emptyStream: ExplanationStream = { versions: [], checking: [], corrections: [] }

function sameUnitVersion(a: UnitReference, b: UnitReference) {
  return a.logical_id === b.logical_id && a.content_version === b.content_version
}

function sameVersion(a: UnitVersion, b: UnitVersion) {
  return a.request_id === b.request_id && a.stage === b.stage
    && a.generation === b.generation && a.document_id === b.document_id
    && a.source_hash === b.source_hash && sameUnitVersion(a.output, b.output)
}

function sameCorrection(a: Correction, b: Correction) {
  return a.block_id === b.block_id && a.old_quote === b.old_quote && a.new_quote === b.new_quote
    && a.reason === b.reason && a.severity === b.severity
}

function addVersion(versions: UnitVersion[], row: UnitVersion) {
  return versions.some((saved) => sameVersion(saved, row)) ? versions : [...versions, row]
}

export function applyExplanationEvent(
  stream: ExplanationStream = emptyStream,
  event: ExplanationEvent,
  sequence?: number,
): ExplanationStream {
  switch (event.type) {
    case "prep_status":
      if (sequence !== undefined && stream.preparationSequence !== undefined
          && sequence <= stream.preparationSequence) return stream
      if (stream.preparation?.status !== "loading" && stream.preparation?.document_id === event.content.document_id
          && event.content.status === "loading") return stream
      return { ...stream, preparation: event.content, preparationSequence: sequence }
    case "unit_draft":
    case "unit_ready": {
      const versions = addVersion(stream.versions, event.content)
      return versions === stream.versions ? stream : { ...stream, versions }
    }
    case "unit_checking":
      return stream.checking.some((value) => sameUnitVersion(value, event.content))
        ? stream : { ...stream, checking: [...stream.checking, event.content] }
    case "unit_correction":
      return stream.corrections.some((value) => sameUnitVersion(value, event.content)
        && value.version_request_id === event.content.version_request_id && value.generation === event.content.generation
        && sameCorrection(value, event.content))
        ? stream : { ...stream, corrections: [...stream.corrections, event.content] }
  }
}

export interface ExplanationTurn {
  requestId: string
  messageId?: string
  checkpointRevision?: number
  saved?: ExplanationV2
  stream: ExplanationStream
}

function withSource(row: UnitVersion, source?: { document_id?: string; generation?: number; source_hash?: string }): UnitVersion {
  return {
    ...row,
    document_id: row.document_id ?? source?.document_id,
    generation: row.generation ?? source?.generation,
    source_hash: row.source_hash ?? source?.source_hash,
  }
}

/** Build the inquiry model from existing messages. Checkpoint call accounting is intentionally omitted. */
export function restoreExplanationTurns(messages: UIMessage[]) {
  const turns = new Map<string, ExplanationTurn>()
  for (const message of messages) {
    if (!record(message.metadata)) continue
    const { explanation, explain_unit_checkpoint: checkpoint, explanationStream: live, request_id: id } = message.metadata
    const saved = explanationV2(explanation)
    const snapshot = record(checkpoint) && Array.isArray(checkpoint.versions) ? checkpoint : undefined
    const requestId = typeof id === "string" ? id : typeof snapshot?.request_id === "string"
      ? snapshot.request_id : message.id
    if (!saved && !snapshot && !live) continue
    const previous = turns.get(requestId)
    const stream = (live as ExplanationStream | undefined) ?? previous?.stream ?? emptyStream
    let versions = previous?.stream.versions ?? []
    if (snapshot) {
      for (const row of snapshot.versions as unknown[]) {
        if (version(row)) {
          // Intermediate checkpoint-only facts are not part of the public draft contract.
          const publicRow = { ...withSource(row, snapshot) }
          delete publicRow.deterministic_facts
          versions = addVersion(versions, publicRow)
        }
      }
    }
    const progress = saved?.course_progress
    for (const row of saved?.versions ?? []) {
      versions = addVersion(versions, withSource(row, { document_id: progress?.document_id,
        generation: progress?.index_generation, source_hash: progress?.source_hash }))
    }
    for (const row of stream.versions) versions = addVersion(versions, row)
    turns.set(requestId, {
      requestId,
      messageId: message.role === "assistant" ? message.id : previous?.messageId,
      checkpointRevision: typeof snapshot?.revision === "number" ? snapshot.revision : previous?.checkpointRevision,
      saved: saved ?? previous?.saved,
      stream: {
        ...stream,
        versions,
        interrupted: saved ? false : stream.interrupted ?? Boolean(snapshot && !live),
      },
    })
  }
  return turns
}

const stageOrder = { draft: 0, repaired: 1, ready: 2 }

export function unitGenerationInterrupted(output: UnitOutput) {
  return output.interruptions?.some((reason) =>
    reason === "provider_failure" || reason === "truncated" || reason === "deadline") === true
}

export function explanationUnits(turn: ExplanationTurn) {
  const units = new Map<string, { current: UnitVersion; versions: UnitVersion[] }>()
  for (const row of turn.stream.versions) {
    const key = JSON.stringify([row.document_id, row.output.logical_id])
    const unit = units.get(key)
    if (!unit) {
      units.set(key, { current: row, versions: [row] })
      continue
    }
    unit.versions.push(row)
    const current = unit.current
    const sameAttempt = current.request_id === row.request_id
    const newerGeneration = (row.generation ?? 0) > (current.generation ?? 0)
    const sameGeneration = row.generation === current.generation
    if (newerGeneration || (sameGeneration && (sameAttempt
      ? stageOrder[row.stage] > stageOrder[current.stage]
      : row.request_id === turn.requestId))) {
      unit.current = row
    }
  }
  return Array.from(units.values(), ({ current, versions }) => {
    const corrections = [...(current.change_log ?? [])]
    for (const change of turn.stream.corrections) {
      if (sameUnitVersion(change, current.output) && (change.version_request_id ?? turn.requestId) === current.request_id
          && (change.generation === undefined || change.generation === current.generation)
          && !corrections.some((value) => sameCorrection(value, change))) corrections.push(change)
    }
    const checking = current.stage === "repaired" || turn.stream.checking.some((row) => sameUnitVersion(row, current.output))
    const saved = turn.saved?.units.find((output) => sameUnitVersion(output, current.output))
    const lifecycle = current.stage === "ready" ? (corrections.length ? "corrected" : "ready")
      : turn.stream.failed ? "failed"
        : turn.stream.interrupted || (saved && unitGenerationInterrupted(saved)) ? "interrupted"
        : saved ? "draft" : checking ? "checking" : "drafting"
    return { current, versions, corrections, lifecycle, stale: turn.saved?.historical_source === true }
  })
}

/** One entry per logical unit and document across Continue/Deepen turns. The latest ledger remains
 * on its originating turn, so overlapping requests cannot replace each other's requested scope. */
export function inquiryExplanationUnits(turns: Map<string, ExplanationTurn>) {
  type Unit = ReturnType<typeof explanationUnits>[number]
  const units = new Map<string, Unit & { lastReady?: UnitVersion }>()
  const requestOrder = new Map(Array.from(turns.keys(), (id, order) => [id, order]))
  for (const turn of turns.values()) {
    for (const unit of explanationUnits(turn)) {
      const { current } = unit
      const key = JSON.stringify([current.document_id, current.output.logical_id])
      const prior = units.get(key)
      const versions = unit.versions.reduce(addVersion, prior?.versions ?? [])
      // Cached rows carry the original request_id while the event envelope carries the replaying turn.
      // Prefer the originating turn when known. A replay alone cannot displace a newer local result.
      const newer = (a: UnitVersion, b: UnitVersion) => {
        if (a.generation !== b.generation) return (a.generation ?? 0) > (b.generation ?? 0)
        if (a.request_id === b.request_id) return stageOrder[a.stage] > stageOrder[b.stage]
        if (!requestOrder.has(a.request_id)) return false
        return (requestOrder.get(a.request_id) ?? -1) > (requestOrder.get(b.request_id) ?? -1)
      }
      const selected = !prior || newer(current, prior.current) || (unit.stale && sameVersion(current, prior.current))
        ? unit : prior
      const corrections = sameVersion(selected.current, current)
        ? unit.corrections.reduce((all, change) => all.some((item) => sameCorrection(item, change)) ? all : [...all, change],
          selected.corrections)
        : selected.corrections
      const lastReady = versions.reduce<UnitVersion | undefined>((latest, row) =>
        row.stage === "ready" && row.output.blocks.length && (!latest || newer(row, latest)) ? row : latest,
      undefined)
      units.set(key, { ...selected, corrections, versions, lastReady,
        lifecycle: selected.current.stage === "ready" && corrections.length ? "corrected" : selected.lifecycle })
    }
    const source = turn.saved?.course_progress
    for (const change of source?.unit_reconciliation ?? []) {
      if (!change.stale) continue
      const key = JSON.stringify([source?.document_id, change.prior_id])
      const previous = units.get(key)
      if (previous && previous.current.generation !== source?.index_generation) {
        units.set(key, { ...previous, stale: true })
      }
    }
  }
  return units
}

export function supportedUnitActions(saved: ExplanationV2) {
  if (saved.historical_source) return []
  return saved.learning_state.next_actions.filter((action) =>
    record(action) && (action.action === "continue_learning" || action.action === "deepen_unit")
    && typeof action.logical_id === "string" && typeof action.request_id === "string")
}
