import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"
import { documentFixture, explanationFixtures, instructionalFixture, phase7Fixture, python } from "./explanation-card-fixtures.mjs"

const require = createRequire(import.meta.url)
const modules = new Map()
const button = ({ children, disabled, onClick, type }) =>
  React.createElement("button", { disabled, onClick, type }, children)
function load(path, overrides = {}) {
  const source = readFileSync(new URL("../" + path, import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } })
  const exports = {}
  new Function("exports", "require", outputText)(exports, (name) => {
    if (name in overrides) return overrides[name]
    if (name === "@/components/ui/button") return { Button: button }
    if (name.startsWith("@/")) {
      const base = name.slice(2)
      const extension = base.startsWith("components/") ? ".tsx" : ".ts"
      const key = base + extension
      if (!modules.has(key)) modules.set(key, load(key))
      return modules.get(key)
    }
    return require(name)
  })
  return exports
}

const { ExplanationCard } = load("components/chat/ExplanationCard.tsx")
const { coverageCopy, explanationCardLayout } = load("lib/ai/explanation-card-layout.ts")
const { explanationProgressKey, readExplanationProgress, writeExplanationProgress } = load("lib/ai/explanation-progress.ts")
const { StudyMarkdown } = load("components/notebook/NotebookReply.tsx")
const { explanationNoteText } = load("lib/ai/explanation-note.ts")
const { readNoteDocument, noteText } = load("lib/notebook/document.ts")
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props))
const {
  applyExplanationEvent, explanationUnits, explanationV2, inquiryExplanationUnits, restoreExplanationTurns,
  supportedUnitActions, unitPresentation,
} = load("lib/explanation-v2.ts")
const { parseServerMessage } = load("lib/socra-ws.ts", {
  "./explanation-v2": load("lib/explanation-v2.ts"), "./educational-document": load("lib/educational-document.ts"),
})
const { ExplanationUnit } = load("components/chat/ExplanationUnit.tsx")
const { explanationDocument } = load("lib/explanation-document.ts")
const { LiveExplanation } = load("components/chat/LiveExplanation.tsx")
const { unitActivityKey, requirementActivityId } = load("components/chat/UnitActivity.tsx")

test("live structured snapshots keep the draft visible through checking and render actual ready coverage", () => {
  const { card, checking } = documentFixture("course")
  const requestId = checking.request_id
  const prep = applyExplanationEvent(undefined, { type: "prep_status", content: { document_id: checking.document_id, status: "loading" } }, 1)
  const draft = applyExplanationEvent(prep, { type: "unit_draft", content: checking }, 2)
  const checked = applyExplanationEvent(draft, { type: "unit_checking", content: checking.output }, 3)
  assert.match(render(LiveExplanation, { french: true, turn: { requestId, stream: prep } }), /Préparation des sources/)
  const draftHtml = render(LiveExplanation, { french: true, turn: { requestId, stream: draft } })
  assert.match(draftHtml, /Génération/)
  const checkingHtml = render(LiveExplanation, { french: true, turn: { requestId, stream: checked } })
  assert.match(checkingHtml, /Vérification/)
  assert.match(checkingHtml, /Provisoire/)
  assert.match(checkingHtml, /Leakage occurs/)
  assert.doesNotMatch(checkingHtml, /Relu indépendamment|Vérification terminée/)
  const ready = { ...checking, stage: "ready", output: { ...checking.output, coverage: "not_generated", blocks: [], interruptions: ["call_budget"] } }
  const after = applyExplanationEvent(checked, { type: "unit_ready", content: ready }, 4)
  const readyHtml = render(LiveExplanation, { french: true, turn: { requestId, stream: after } })
  assert.match(readyHtml, /À venir/)
  assert.match(readyHtml, /Limite de génération atteinte/)
  assert.match(readyHtml, /Vérification terminée/)
  assert.doesNotMatch(readyHtml, /✓ Expliquée?|Relu indépendamment/)
  const interruption = render(LiveExplanation, { french: true, turn: { requestId, stream: { ...checked, interrupted: true, failed: true } } })
  assert.match(interruption, /La génération s’est arrêtée/)
  assert.doesNotMatch(interruption, /Limite de génération/)
  const linked = explanationDocument(card, { live: { requestId, stream: checked } })
  assert.equal(linked.units.get(checking.output.logical_id).lifecycle, "checking")
  assert.equal(linked.counts.explained, 2)
})

test("a systemic provider corruption stop explains why the text could not be retained", () => {
  const { card } = documentFixture("course")
  const [unit, ...rest] = card.units
  const explanation = { ...card, units: [{ ...unit, blocks: [], coverage: "not_generated",
    interruptions: ["systemic_generation_failure", "provider_text_corruption"] }, ...rest] }
  assert.match(render(ExplanationCard, { explanation }),
    /Le fournisseur a renvoyé du texte corrompu\. L’explication concernée n’a pas pu être conservée/)
  assert.match(render(ExplanationCard, { explanation: { ...explanation, language: "English" } }),
    /The provider returned corrupted text\. The affected explanation could not be safely retained\./)
})

test("high-severity corrections keep quotations, source references and earlier versions accessible", () => {
  const card = instructionalFixture("concept")
  const [current] = card.versions
  const [block] = current.output.blocks
  const earlier = { ...current, stage: "draft", output: { ...current.output, coverage: "partial", verification: "unreviewed",
    blocks: [{ ...block, text: "Original educational text." }] } }
  const change = { block_id: block.block_id, reason: "review_repair", severity: "high",
    old_quote: "Earlier claim.", new_quote: "Corrected claim." }
  const corrected = { ...current, change_log: [change] }
  const explanation = { ...card, versions: [corrected] }
  const turn = { requestId: current.request_id, stream: { versions: [earlier, corrected], corrections: [], checking: [] } }
  const html = render(ExplanationCard, { explanation, unitContext: { turn } })
  assert.match(html, /<details open=""[^>]*>.*Contenu corrigé/)
  assert.match(html, /<del>Earlier claim\.<\/del>/)
  assert.match(html, /<ins[^>]*>Corrected claim\.<\/ins>/)
  assert.match(html, /Correction après relecture/)
  assert.match(html, /Historique des versions.*Version antérieure.*Original educational text/)
  assert.match(html, /page=12#page=12/)
})

test("Deepen keeps the existing answer readable until an exact-source replacement is ready", () => {
  const { card } = documentFixture("course")
  const original = card.versions.find(({ output }) => output.coverage === "partial")
  const next = { ...original, request_id: "deepen-live", stage: "draft", output: { ...original.output,
    blocks: [{ ...original.output.blocks[0], text: "New provisional reasoning." }] } }
  const turn = { requestId: next.request_id, stream: { versions: [next], checking: [next.output], corrections: [] } }
  const id = original.output.logical_id
  const during = explanationDocument(card, { live: turn }).units.get(id)
  assert.deepEqual(during.output.blocks, original.output.blocks)
  assert.equal(during.provisionalVersion.output.blocks[0].text, "New provisional reasoning.")
  const ready = { ...next, stage: "ready" }
  const after = explanationDocument(card, { live: { ...turn, stream: { ...turn.stream, versions: [next, ready] } } }).units
  assert.equal(after.get(id).output.blocks[0].text, "New provisional reasoning.")
  assert.equal([...after.values()].filter((unit) => unit.id === id).length, 1)
  assert.ok(after.get(id).history.some((row) => row.request_id === original.request_id))
})

test("activity is scoped to the owner, source generation and requirement without changing the verdict", () => {
  const { card } = documentFixture("lab")
  const [unit] = card.units
  const scope = { ownerId: "student-a", documentId: "pdf", generation: 3, sourceHash: "hash" }
  const key = unitActivityKey(scope, unit, "read")
  assert.notEqual(key, unitActivityKey({ ...scope, ownerId: "student-b" }, unit, "read"))
  assert.notEqual(key, unitActivityKey({ ...scope, generation: 4 }, unit, "read"))
  assert.notEqual(requirementActivityId("checkpoint", "save a workflow"), requirementActivityId("checkpoint", "save three workflows"))
  assert.equal(unitActivityKey({ ...scope, ownerId: undefined }, unit, "read"), "")
  const html = render(ExplanationCard, { explanation: card, ownerId: scope.ownerId })
  assert.match(html, /Marquer comme relu/)
  assert.match(html, /J’ai effectué ce contrôle/)
  assert.match(html, /J’ai produit ce livrable/)
  assert.match(html, /1 sur 4 étapes expliquées/)
  assert.doesNotMatch(render(ExplanationCard, { explanation: card, ownerId: scope.ownerId, readOnly: true }), /type="checkbox"/)
  const stale = render(ExplanationCard, { explanation: { ...card, historical_source: true }, ownerId: scope.ownerId, onUnitAction: () => {} })
  assert.match(stale, /version historique/)
  assert.doesNotMatch(stale, /data-coverage-total|type="checkbox"|Continuer :|href="\/api\/documents\/view/)
})

const instructionalKinds = ["concept", "derivation", "worked_calculation", "comparison", "figure_walkthrough",
  "rule_examples", "exercise", "lab_step", "research_finding"]

test("all nine instructional kinds render their supplied blocks without repeating the legacy projection", () => {
  for (const kind of instructionalKinds) {
    const explanation = instructionalFixture(kind)
    const html = render(ExplanationCard, { explanation })
    assert.ok(html.includes(`data-explanation-unit="${kind}"`), kind)
    for (const block of explanation.units[0].blocks) {
      assert.ok(html.includes(`data-explanation-block="${block.kind}"`), `${kind}/${block.kind}`)
    }
    assert.doesNotMatch(html, /Legacy projection marker|Legacy sample content/)
  }
  const concept = render(ExplanationCard, { explanation: instructionalFixture("concept") })
  inOrder(concept, "Leakage occurs", "Imagine reading", "Training", "Fit preprocessing")
  const derivation = render(ExplanationCard, { explanation: instructionalFixture("derivation") })
  assert.match(derivation, /<ol[^>]*>.*Write the reciprocal sum/)
  assert.match(derivation, /class="katex-display"/)
  const calculation = render(ExplanationCard, { explanation: instructionalFixture("worked_calculation") })
  assert.match(calculation, /class="katex-display"/)
  assert.doesNotMatch(calculation, /<pre/)
  const comparison = render(ExplanationCard, { explanation: instructionalFixture("comparison") })
  assert.match(comparison, /overflow-x-auto[^>]*>\s*<table/)
  inOrder(comparison, "Method A", "Method B", "Method C", "Local", "Global", "Both")
  const lab = render(ExplanationCard, { explanation: instructionalFixture("lab_step") })
  assert.match(lab, /Copier le code/)
  inOrder(lab, "Get-Content", "Résultat attendu", "Point de contrôle")
  assert.doesNotMatch(lab, /<input/)
  assert.match(render(ExplanationCard, { explanation: instructionalFixture("exercise") }), /Copier la réponse/)
})

test("structured provenance and page links are bound to valid block anchors", () => {
  const { units: [output], versions: [version] } = instructionalFixture("rule_examples")
  const html = render(ExplanationUnit, { output, identity: version.identity, documentId: "right-document", french: true })
  inOrder(html, "Source example.", "/api/documents/view/right-document?page=12#page=12",
    "Explication Socra, hors du PDF", "Exemple hypothétique de Socra, pas le calcul du PDF", "Additional example.")
  const bad = { ...output, blocks: [{ ...output.blocks[0], source_indexes: [0, 2, 1.5] }] }
  assert.doesNotMatch(render(ExplanationUnit, { output: bad, documentId: "right-document", french: true }), /href=|Sources du bloc/)
  const wrongOffset = { ...output, sources: [{ page: 3, start: 20, end: 5, quote: "Bad" }] }
  assert.doesNotMatch(render(ExplanationUnit, { output: wrongOffset, documentId: "right-document", french: true }), /href=/)
  const checkedFixture = instructionalFixture("worked_calculation")
  checkedFixture.units[0].blocks.find(block => block.kind === "calculation").calculation = { expression: "9/12", expected: 0.75 }
  const checked = render(ExplanationCard, { explanation: checkedFixture })
  assert.match(checked, /Dérivé · recalculé/)
  assert.doesNotMatch(render(ExplanationCard, { explanation: instructionalFixture("lab_step") }), /Dérivé · recalculé/)
})

test("unverified readings, readiness, coverage and review remain distinct", () => {
  const fixture = instructionalFixture("figure_walkthrough")
  const html = render(ExplanationCard, { explanation: fixture })
  for (const label of ["Source non vérifiable", "p. 12", "Non vérifié", "Non relue", "◐ Partiel",
    "Valeurs lues sur le graphique : approximatives", "Éléments manquants (1)"]) assert.ok(html.includes(label), label)
  assert.match(html, /page=12#page=12/)
  assert.doesNotMatch(html, /<img|✓ Expliqué|Relu indépendamment/)
  const [output] = fixture.units
  const props = { french: true, output: { ...output, coverage: "explained", verification: "review_failed",
    unverifiable_source: [], missing_item_ids: [] } }
  assert.match(render(ExplanationUnit, props), /✓ Expliqué.*Non relue/)
  assert.match(render(ExplanationUnit, { ...props, output: { ...props.output, coverage: "partial", verification: "reviewed" } }),
    /◐ Partiel.*Relu indépendamment/)
  const unavailable = render(ExplanationUnit, { ...props, output: { ...props.output, coverage: "not_generated",
    verification: "unreviewed", blocks: [] } })
  assert.match(unavailable, /À venir/)
  assert.doesNotMatch(unavailable, /Expliqué|data-explanation-block=/)
})

test("Spark lab checks and independent review preserve the backend's draft and ready states", () => {
  const fixture = instructionalFixture("lab_step")
  const [output] = fixture.units
  const [version] = fixture.versions
  const draft = { ...output, coverage: "partial", review_state: "incomplete",
    lab_verification: { checks: { runtime_qualification: false, source_grounding: false, control_characters: true } } }
  const renderUnit = (output, stage) => render(ExplanationUnit, { output, identity: version.identity, french: true, stage })
  const incomplete = renderUnit(draft)
  assert.match(incomplete, /Contrôles automatiques.*1\/3.*Relecture incomplète.*Brouillon/)
  assert.match(incomplete, /Version relevée à l’exécution.*Échec/)
  assert.doesNotMatch(incomplete, /Approuvé|Score pédagogique/)
  const approved = renderUnit({ ...draft, review_state: "approved", verification: "reviewed",
    lab_verification: { checks: { runtime_qualification: true, source_grounding: true, control_characters: true } },
    independent_review: { pedagogy_score: 2, lab_evidence: [{ quote: "Deux threads sur un seul poste." }] } }, "ready")
  for (const label of ["3/3", "Approuvé", "Prêt", "Score pédagogique", "Éléments de preuve de la relecture",
    "Deux threads sur un seul poste."]) assert.ok(approved.includes(label), label)
})

test("a saved partial stream reports the interruption instead of ongoing generation", () => {
  const saved = instructionalFixture("lab_step")
  const [output] = saved.units
  saved.units[0] = { ...output, coverage: "partial", interruptions: ["provider_failure"] }
  const html = render(LiveExplanation, { french: true, turn: {
    requestId: "interrupted", saved, stream: { versions: [], checking: [], corrections: [] },
  } })
  assert.match(html, /Génération interrompue/)
  assert.doesNotMatch(html, /Génération du contenu|Vérification du contenu/)
})

test("both beeswarm source gaps remain visible without fabricated findings", () => {
  const [output] = instructionalFixture("figure_walkthrough").units
  const html = render(ExplanationUnit, { output: { ...output, blocks: [], sources: [], missing_item_ids: [],
    unverifiable_source: [
      { page: 18, status: "unverifiable_source", label: "Libellés et valeurs des variables du graphique" },
      { page: 18, status: "unverifiable_source", label: "Libellé de l’axe horizontal du graphique" },
    ] }, french: true })
  inOrder(html, "Source non vérifiable", "p. 18", "Libellés et valeurs des variables du graphique",
    "Libellé de l’axe horizontal du graphique")
  assert.doesNotMatch(html, /Éléments manquants|data-explanation-block=/)
})

test("optional, unknown and non-teaching blocks stay readable without empty sections", () => {
  const { units: [output], versions: [version] } = instructionalFixture("concept")
  const withBlocks = { ...output, blocks: [
    { ...output.blocks[0], kind: "intuition", text: " " },
    { ...output.blocks[1], kind: "constructor", text: "A new instructional block." },
  ] }
  const props = { output: withBlocks, identity: { ...version.identity, kind: "future_kind" }, french: true }
  const html = render(ExplanationUnit, props)
  assert.match(html, /data-explanation-unit="unknown".*A new instructional block/)
  assert.doesNotMatch(html, /Intuition|Copier la réponse/)
  const recap = render(ExplanationUnit, { ...props, identity: { ...version.identity, kind: "summary" } })
  assert.match(recap, /<details><summary/)
  assert.doesNotMatch(recap, /✓ Expliqué|Relu indépendamment/)
  const transition = render(ExplanationUnit, { ...props, identity: { ...version.identity, kind: "transition" } })
  assert.match(transition, /data-explanation-unit="non_teaching"/)
  assert.doesNotMatch(transition, /<details>|A new instructional block/)
})

test("Phase 7 payloads retain backend progress, provenance, sources and unknown extensions", () => {
  for (const scenario of ["course", "exercises", "lab"]) {
    const { card, draft } = phase7Fixture(scenario)
    const parsed = explanationV2({ ...card, additional_field: { future: true } })
    assert.deepEqual(parsed.additional_field, { future: true })
    assert.equal(parsed.units[0].blocks[1].hypothetical, true)
    assert.equal(parsed.units[0].blocks[1].provenance, "supplementary")
    assert.equal(parsed.units[0].sources[parsed.units[0].blocks[0].source_indexes[0] - 1].page, 1)
    assert.deepEqual(parsed.coverage_ledger.low_fidelity_pages, [1])
    const message = (content) => JSON.stringify({
      type: "unit_draft", content, session_id: "session", request_id: draft.request_id, sequence: 3,
    })
    const withoutOptional = { ...draft }
    delete withoutOptional.change_log
    assert.deepEqual(parseServerMessage(message(withoutOptional)).content, withoutOptional)
    assert.equal(parseServerMessage(message({ ...withoutOptional, output: { ...draft.output, blocks: null } })), null)
    assert.equal(parsed.versions[0].document_id, card.course_progress.document_id)
    assert.equal(parsed.versions[0].generation, 4)
    assert.equal(supportedUnitActions(parsed)[0].logical_id, parsed.coverage_ledger.remaining[0].logical_id)
    if (scenario === "exercises") assert.equal(parsed.learning_state.progress[2].scope_reason, "exercise_excluded")
  }
  assert.equal(unitPresentation("new_kind"), "unknown")
  for (const kind of ["transition", "front_matter", "summary"]) assert.equal(unitPresentation(kind), "non_teaching")
  for (const kind of ["concept", "derivation", "worked_calculation", "comparison", "figure_walkthrough",
    "rule_examples", "exercise", "lab_step", "research_finding"]) assert.equal(unitPresentation(kind), kind)
})

test("saved checkpoint and assistant metadata merge with replay and retain corrected version history", () => {
  const { card, draft, snapshot, change } = phase7Fixture()
  const request_id = draft.request_id
  const prompt = { id: "prompt", role: "user", metadata: { request_id, explain_unit_checkpoint: snapshot } }
  const assistant = { id: "saved", role: "assistant", metadata: { request_id, explanation: card } }
  const legacy = { id: "old", role: "assistant", metadata: { explanation: explanationFixtures.standard } }
  const [interrupted] = restoreExplanationTurns([prompt]).values()
  assert.equal(interrupted.stream.interrupted, true)
  assert.equal(interrupted.stream.versions.length, snapshot.versions.length)
  assert.equal(interrupted.stream.calls, undefined)
  const ready = card.versions[0]
  const replay = applyExplanationEvent(undefined, { type: "unit_ready", content: { ...ready, replayed: true } })
  const turns = restoreExplanationTurns([legacy, prompt, { ...assistant,
    metadata: { ...assistant.metadata, explanationStream: replay } }])
  assert.equal(turns.size, 1)
  assert.equal(explanationV2(legacy.metadata.explanation), undefined)
  const turn = turns.get(request_id)
  const [unit] = explanationUnits(turn)
  assert.equal(turn.messageId, "saved")
  assert.equal(turn.saved.coverage_ledger.coverage_counts.partial, 1)
  assert.equal(unit.lifecycle, "corrected")
  assert.equal(unit.current.output.coverage, "partial")
  assert.equal(unit.current.output.verification, "review_failed")
  assert.deepEqual(unit.current.output.missing_item_ids, draft.output.missing_item_ids)
  assert.deepEqual(unit.current.output.unverifiable_source, draft.output.unverifiable_source)
  assert.equal(unit.versions.length, 2)
  assert.deepEqual(unit.corrections, [change])
})

test("checking and correction events reconcile regardless of ordering and remain scoped by request", () => {
  const { card, draft, change } = phase7Fixture("lab")
  const requestId = draft.request_id
  const ready = { ...card.versions[0], change_log: [] }
  const checking = applyExplanationEvent(undefined, { type: "unit_checking", content: draft.output })
  const drafting = applyExplanationEvent(checking, { type: "unit_draft", content: draft })
  assert.equal(explanationUnits({ requestId, stream: drafting })[0].lifecycle, "checking")
  assert.equal(explanationUnits({ requestId, stream: { ...drafting, interrupted: true } })[0].lifecycle, "interrupted")
  const completed = applyExplanationEvent(drafting, { type: "unit_ready", content: ready })
  const correction = { type: "unit_correction", content: { ...change, logical_id: ready.output.logical_id,
    content_version: ready.output.content_version, generation: ready.generation, version_request_id: requestId } }
  const corrected = applyExplanationEvent(completed, correction)
  assert.equal(applyExplanationEvent(corrected, correction), corrected)
  assert.equal(explanationUnits({ requestId, stream: corrected })[0].lifecycle, "corrected")
  const deepen = "deepen"
  const other = applyExplanationEvent(undefined, { type: "unit_draft", content: { ...draft, request_id: deepen } })
  const replays = applyExplanationEvent(other, { type: "unit_ready", content: { ...ready, replayed: true } })
  const combined = inquiryExplanationUnits(new Map([
    [requestId, { requestId, stream: corrected }], [deepen, { requestId: deepen, stream: replays }],
  ]))
  assert.equal(combined.size, 1)
  const [unit] = combined.values()
  assert.equal(unit.current.request_id, deepen)
  assert.equal(unit.lastReady.request_id, requestId)
  assert.equal(unit.versions.length, 3)
})

test("v2 compatibility card labels Continue from the backend action and hides historical actions", () => {
  const { card } = phase7Fixture()
  const props = { onDiscuss: () => {}, onUnitAction: () => {} }
  const html = render(ExplanationCard, { ...props, explanation: card })
  assert.match(html, /Continuer : II\.2/)
  assert.doesNotMatch(html, /Continuer avec la partie/)
  assert.match(html, /À venir/)
  assert.doesNotMatch(html, /Part II \(p\./)
  const exercises = render(ExplanationCard, { ...props, explanation: phase7Fixture("exercises").card })
  assert.match(exercises, /Hors demande/)
  const historical = render(ExplanationCard, { ...props, explanation: { ...card, historical_source: true } })
  assert.doesNotMatch(historical, /Continuer : II\.2/)
  assert.deepEqual(supportedUnitActions({ ...card, learning_state: { ...card.learning_state,
    next_actions: [{ action: "explain_unit", logical_id: "unit", request_id: "request" }] } }), [])
})

test("course shell uses Part II source labels and a complete eligible denominator", () => {
  const { card, checking } = documentFixture("course")
  const context = { checking: [checking], source: { title: "Post-hoc interpretation", pageCount: 11 } }
  const model = explanationDocument(card, context)
  assert.equal(model.shell, "course")
  assert.deepEqual(model.counts, { total: 7, explained: 2, partial: 1, notGenerated: 4 })
  assert.deepEqual(model.groups.map(({ label }) => label), ["II"])
  assert.equal(model.checking, 1)
  assert.equal(model.units.get(checking.output.logical_id).progress.status, "not_generated")
  assert.equal(model.excluded.length, 3)
  const html = render(ExplanationCard, { explanation: card, unitContext: context, onUnitAction: () => {} })
  assert.match(html, /2 sur 7 unités expliquées/)
  assert.match(html, /1 en vérification/)
  assert.match(html, /Profondeur exhaustive/)
  assert.match(html, /Hypothèse/)
  assert.match(html, /Plan du cours/)
  assert.match(html, /11 pages/)
  inOrder(html, 'data-document-unit="course-1"', 'data-document-unit="course-2"', 'data-document-unit="course-3"',
    'data-document-unit="course-4"', 'data-document-unit="course-5"')
  assert.match(html, /Part I · Fundamentals/)
  assert.match(html, /Part III · Interpretable models/)
  assert.match(html, /Part IV · Auditability/)
  assert.match(html, /Tout développer/)
  assert.match(html, /Tout réduire/)
  assert.match(html, /Approfondir II\.3/)
  assert.match(html, /Continuer : II\.4/)
  assert.doesNotMatch(html, /Legacy projection only|Duplicate fallback content|Expliquer maintenant/)
  const reordered = { ...card, course_progress: { ...card.course_progress, learning_plan: {
    ...card.course_progress.learning_plan, order: ["course-3", "course-2", "course-1"],
  } } }
  assert.deepEqual(explanationDocument(reordered).included.slice(0, 3).map(({ id }) => id), ["course-3", "course-2", "course-1"])
})

test("exercise shell keeps question groups, sheet exclusions and verified facts separate", () => {
  const { card } = documentFixture("exercises")
  const model = explanationDocument(card)
  assert.deepEqual(model.groups.map(({ label, units }) => [label, units.length]), [["1", 3], ["2", 3]])
  assert.equal(model.counts.total, 6)
  assert.equal(model.excluded[0].progress.scope_reason, "exercise_excluded")
  assert.deepEqual(model.results.map(({ label, value }) => [label, value]), [["1.b", "0,80"]])
  const html = render(ExplanationCard, { explanation: card, onUnitAction: () => {} })
  assert.match(html, /data-explanation-shell="exercises"/)
  assert.match(html, /4 questions sur 6 répondues/)
  assert.match(html, /Utilise 1.a/)
  assert.match(html, /Résultats obtenus/)
  assert.match(html, /0,80/)
  assert.match(html, /Ignoré à votre demande/)
  assert.match(html, /Continuer : 2.b/)
  assert.match(html, /Compléter 2.a/)
  assert.doesNotMatch(html, /Résoudre quand même|invalid sample value/)
})

test("lab roadmap uses supplied commands, checkpoints and deliverables as read-only requirements", () => {
  const { card } = documentFixture("lab")
  const html = render(ExplanationCard, { explanation: card, onUnitAction: () => {} })
  assert.match(html, /data-explanation-shell="lab"/)
  assert.match(html, /1 sur 4 étapes expliquées/)
  assert.match(html, /Livrables demandés/)
  assert.match(html, /Livrable demandé/)
  assert.match(html, /Save the configured KNIME workflow/)
  assert.match(html, /Point de contrôle/)
  assert.match(html, /Source non vérifiable/)
  assert.match(html, /Continuer : Étape 3/)
  assert.doesNotMatch(html, /<input|Livrable terminé/)
})

test("missing classification and ledger omit invented totals while retaining genuine unit content", () => {
  const { card, checking } = documentFixture("course")
  const oldSource = { ...checking, generation: checking.generation + 1 }
  const current = { ...card, course_progress: { ...card.course_progress, sections: [], learning_plan: undefined },
    versions: [], coverage_ledger: { ...card.coverage_ledger, coverage_counts: { explained: 2 } } }
  const model = explanationDocument(current, { checking: [oldSource] })
  assert.equal(model.shell, "neutral")
  assert.equal(model.counts, undefined)
  assert.equal(model.checking, 0)
  const html = render(ExplanationCard, { explanation: current })
  assert.match(html, /data-explanation-shell="neutral"/)
  assert.match(html, /Shapley value calculation/)
  assert.doesNotMatch(html, /data-coverage-total|Tout développer/)
})

test("the full progress roster identifies a scoped chapter and a mixed practical lab", () => {
  const { card } = documentFixture("course")
  const progress = card.learning_state.progress.map((row) => ({ ...row,
    kind: row.scope_reason === "non_teaching" ? "summary" : "concept",
  }))
  const scoped = { ...card, course_progress: { ...card.course_progress, sections: card.course_progress.sections.slice(0, 1) },
    versions: card.versions.slice(0, 1), learning_state: { ...card.learning_state, progress } }
  assert.equal(explanationDocument(scoped).shell, "course")

  const { card: lab } = documentFixture("lab")
  const extra = [
    { ...lab.learning_state.progress[0], logical_id: "lecture-1", kind: "concept" },
    { ...lab.learning_state.progress[0], logical_id: "lecture-2", kind: "concept" },
    { ...lab.learning_state.progress[0], logical_id: "practice-1", kind: "exercise" },
    { ...lab.learning_state.progress[0], logical_id: "practice-2", kind: "exercise" },
  ]
  const mixed = { ...lab, learning_state: { ...lab.learning_state, progress: [...lab.learning_state.progress, ...extra] } }
  assert.equal(explanationDocument(mixed).shell, "lab")
  extra[0].kind = undefined
  assert.equal(explanationDocument(mixed).shell, "neutral")
})

test("a course can expand a previously generated exercise and rejects earlier source generations", () => {
  const { card } = documentFixture("course")
  const row = card.learning_state.progress.find((row) => row.logical_id === "course-5")
  const identity = card.course_progress.sections.find((row) => row.id === "course-5")
  const [base] = instructionalFixture("exercise").units
  row.status = "explained"
  const earlier = { ...card.versions[0], identity, request_id: "previous-turn",
    output: { ...base, logical_id: row.logical_id, content_version: row.content_version, title: row.title } }
  const model = explanationDocument(card, { previous: [earlier] })
  assert.equal(model.shell, "course")
  assert.ok(model.units.get(row.logical_id).output.blocks.some((block) => block.kind === "final_answer"))
  const html = render(ExplanationCard, { explanation: card, unitContext: { previous: [earlier] } })
  assert.match(html, /data-explanation-unit="exercise"/)
  assert.equal(explanationDocument(card, { previous: [{ ...earlier, generation: earlier.generation - 1 }] })
    .units.get(row.logical_id).output, undefined)
})

test("brief metadata preserves a compact table and source order, and keeps extras optional", () => {
  const html = render(ExplanationCard, { explanation: explanationFixtures.brief, onDiscuss: () => {} })
  inOrder(html, "The exercise compares", "<table", "Copy as Markdown", "?page=2#page=2", "?page=7#page=7")
  assert.match(html, /data-explanation-card="compact"/)
  assert.match(html, /<details[^>]+>\s*<summary[^>]+>Common pitfalls/)
  assert.doesNotMatch(html, /Expand all|<progress/)
})

test("standard sourced measurements render as labelled values without walkthrough controls", () => {
  const html = render(ExplanationCard, { explanation: explanationFixtures.standard })
  inOrder(html, "Why normalize", "Scaling makes distances", "<ol", "Expected results", "<dl", "0.478", "0.780")
  assert.doesNotMatch(html, /Expand all|<progress/)
})

test("saved overflow notices and French templates preserve their full text in the card and Notebook", () => {
  const table = "| Modèle évalué | Après amélioration |\n| --- | --- |\n| 1 250 lignes | |"
  const explanation = {
    ...explanationFixtures.brief, common_pitfalls: [], check_question: "",
    sections: [{ heading: "Résumé", content: table }],
    coverage_notices: [{ heading: "Coverage check", content: "Insufficiently covered requirements. (1).\n- **Missing** — Appendix A (p. 8)" }],
  }
  const saved = JSON.parse(JSON.stringify(explanation))
  const html = render(ExplanationCard, { explanation: saved })
  assert.match(html, /Explanation incomplete/)
  inOrder(html, "Appendix A", "Modèle évalué", "Après amélioration", "1 250 lignes", "Copy as Markdown")
  assert.ok(explanationNoteText(saved).includes(table))
  assert.match(explanationNoteText(saved), /Appendix A \(p\. 8\)/)
})

test("adjacent repeated part labels group without dropping any bodies or their original export headings", () => {
  const original = explanationFixtures.guide
  const sections = [
    { ...original.sections[1], heading: "Part 1: Tools — Setup" },
    { ...original.sections[2], heading: "Part 1: Tools — Inspect data" },
    ...original.sections.slice(3),
  ]
  const explanation = { ...original, sections }
  const html = render(ExplanationCard, { explanation })
  inOrder(html, "Part 1: Tools", "Setup", "Open the Orange workspace.", "Inspect data", "Capture the distribution")
  assert.equal(html.split("Part 1: Tools").length, 2)
  assert.match(explanationNoteText(explanation), /Part 1: Tools — Inspect data/)
})

test("walkthrough groups authored phases and pairs only compact setup content", () => {
  const html = render(ExplanationCard, { explanation: explanationFixtures.guide })
  assert.equal(html.match(/<details open="" data-explanation-collapse/g)?.length, 1)
  assert.equal(html.match(/data-explanation-collapse/g)?.length, 3)
  assert.equal(html.match(/data-explanation-setup/g)?.length, 1)
  assert.match(html, /0 of 4 tasks checked/)
  assert.doesNotMatch(html, /checked=""/)
  assert.match(html, /Collapse all/)
  inOrder(html, "Part 1", "Step 1", "Before you begin", "Run in PowerShell", "Step 2", "Part 2", "Python code", "Deliverables", "<table")
  const legacy = { ...explanationFixtures.guide, sections: [
    ...explanationFixtures.guide.sections,
    { heading: "Appendix", content: "The vector index [7] is intentional." },
  ] }
  assert.match(render(ExplanationCard, { explanation: legacy }), /index \[7\]/)
})
const fence = "~~~"
const citation = { document_id: "00000000-0000-0000-0000-000000000001",
  filename: "Lab [guide].pdf", page_number: 9, excerpt: "Capture the finished settings panel." }

const mixed = [
  "1. Open the app.", fence + "powershell", "Write-Output ready", fence,
  "2. Click Run.", fence + "bash", "echo done", fence,
  "", "| Name | Value |", "| --- | --- |", "| Result | 42 |", "", "Read **the value** $x^2$.",
].join("\n")
const card = {
  definition: "", intuition: " ", course_example: "", common_pitfalls: [], check_question: "",
  sections: [
    { heading: "Setup", content: mixed, code: "Write-Output ready", code_language: "powershell",
      walkthrough: [{ code: "echo done", explanation: "Reports completion." }], citations: [citation], covers: ["step:2"] },
    { heading: "Screenshot checkpoint 2", content: "Capture the settings after running the app.\n\n![Spoof](https://example.com/image.png)",
      citations: [citation] },
    { heading: "Expected results", content: "The sample workflow shows 42.",
      citations: [{ ...citation, excerpt: "The completed example shows 42." }] },
    { heading: "Incomplete explanation", content: "Exercises not covered: Exercise 3. Ask to continue." },
  ],
  citations: [{ ...citation, page_number: 2 }],
}

function inOrder(value, ...parts) {
  let previous = -1
  for (const part of parts) {
    const next = value.indexOf(part, previous + 1)
    assert.ok(next > previous, "Out of order or missing: " + part)
    previous = next
  }
}

test("final and reopened Library cards render ordered Markdown, cited checkpoints and B2 notices", () => {
  for (const explanation of [card, JSON.parse(JSON.stringify({ explanation: card })).explanation]) {
    const html = render(ExplanationCard, { explanation, readOnly: true })
    inOrder(html, "Open the app.", "Run in PowerShell", "Write-Output ready", "Click Run.", "Bash", "echo done", "Reports completion.")
    assert.equal(html.match(/Write-Output ready/g)?.length, 1)
    assert.equal(html.match(/echo done/g)?.length, 1)
    assert.match(html, /<ol start="2"/)
    assert.match(html, /<table/)
    assert.match(html, /<strong>the value<\/strong>/)
    assert.match(html, /class="katex"/)
    assert.match(html, /\?page=9#page=9/)
    assert.match(html, /\?page=2#page=2/)
    assert.match(html, /Screenshot source/)
    assert.match(html, /Source reference/)
    assert.match(html, /Exercises not covered: Exercise 3/)
    assert.doesNotMatch(html, /<img|example\.com|>Definition<|>Intuition<|Check your understanding|step:2/)
  }
})

test("legacy cards use language labels and show GUI-only comments as ordered instructions", () => {
  const old = { ...card, definition: "Old definition.", intuition: "Old intuition.",
    sections: [{ heading: "Solution", code: "print(1)", code_language: "python" },
      { heading: "Click through", code: "# Open the app.\n# Click Run.", code_language: "python" }] }
  const html = render(ExplanationCard, { explanation: old, readOnly: true })
  inOrder(html, "Old definition.", "Python code", "print(1)", "Click through", "<ol", "<li>Open the app.", "<li>Click Run.")
  assert.equal(html.match(/Python code/g)?.length, 1)
  assert.doesNotMatch(html, /# Click Run|Complete code for this exercise/)
  const note = explanationNoteText(old)
  assert.match(note, /1\. Open the app\.\n2\. Click Run\./)
  assert.doesNotMatch(note, /# Click Run/)
})

test("comment-only placeholders render as prose without hiding real scripts", () => {
  const old = { ...card, sections: [
    { heading: "Interface", content: "Open the application.", code: "# Configured in the GUI.", code_language: "python" },
    { heading: "Script", content: fence + "python\n# A genuine script with comments\nprint(42)\n" + fence },
  ] }
  const html = render(ExplanationCard, { explanation: old, readOnly: true })
  inOrder(html, "Configured in the GUI.", "Python code", "print(42)")
  assert.equal(html.match(/Copy code/g)?.length, 1)
  assert.doesNotMatch(html, /# Configured in the GUI/)
  const note = explanationNoteText(old)
  assert.match(note, /Configured in the GUI\./)
  assert.doesNotMatch(note, /# Configured in the GUI/)
})

test("streaming Markdown handles an open fence and final card supersedes the draft", () => {
  const preview = "1. Open the app.\n" + fence + "powershell\nWrite-Output read"
  const html = render(StudyMarkdown, { content: preview })
  inOrder(html, "Open the app.", "Run in PowerShell", "Write-Output read")
  const TutorMessage = load("components/chat/TutorMessage.tsx").TutorMessage
  const { Message } = load("components/chat/Message.tsx", { "./TutorMessage": { TutorMessage },
    "./StudentMessage": { StudentMessage: () => null } })
  const message = { role: "assistant", parts: [{ type: "text", text: preview }], metadata: { explanationPreview: true } }
  assert.match(render(Message, { message, isStreaming: true }), /Run in PowerShell/)
  assert.equal(render(Message, { message: { ...message, metadata: { ...message.metadata, explanation: card } } }), "")
})

test("Notebook conversion keeps fences in place, links and math after reload", () => {
  const markdown = explanationNoteText(card)
  inOrder(markdown, "Open the app.", "~~~powershell", "Write-Output ready", "Click Run.", "~~~bash", "echo done",
    "Reports completion.", "?page=9#page=9", "Screenshot checkpoint", "Exercises not covered: Exercise 3")
  assert.equal(markdown.match(/Write-Output ready/g)?.length, 1)
  const note = readNoteDocument(null, markdown, true)
  const reloaded = readNoteDocument(JSON.parse(JSON.stringify(note)), "")
  const nodes = JSON.stringify(reloaded)
  assert.match(nodes, /"language":"powershell"/)
  assert.match(nodes, /"language":"bash"/)
  assert.match(nodes, /"type":"inlineMath","attrs":\{"latex":"x\^2"\}/)
  assert.match(nodes, /\?page=9#page=9/)
  assert.match(noteText(reloaded), /Exercises not covered: Exercise 3/)
  const overflow = { ...card, course_example: "Checked against retrieved excerpts only.\nInsufficiently covered requirements. Ask to continue with these items (1): question:3.\n\nCourse example here." }
  assert.match(render(ExplanationCard, { explanation: overflow, readOnly: true }), /<aside[^>]+>[\s\S]*?Insufficiently covered requirements/)
  assert.match(explanationNoteText(overflow), /## Coverage notice\n\nChecked against retrieved excerpts only/)
})

test("Copy code copies the actual block text and reports success", async () => {
  let copied
  let status
  const { StudyCopy } = load("components/notebook/NotebookReply.tsx", {
    react: { useState: () => ["", (value) => { status = value }], memo: (component) => component },
  })
  const saved = Object.getOwnPropertyDescriptor(globalThis.navigator, "clipboard")
  Object.defineProperty(globalThis.navigator, "clipboard", { configurable: true, value: {
    writeText: async (value) => { copied = value },
  } })
  try {
    const action = StudyCopy({ value: "  Write-Output ready\n", label: "Copy code" })
    await action.props.onClick()
    assert.equal(copied, "  Write-Output ready\n")
    assert.equal(status, "Copied")
  } finally {
    if (saved) Object.defineProperty(globalThis.navigator, "clipboard", saved)
    else delete globalThis.navigator.clipboard
  }
})

test("all five fixtures use the shared card and reveal only content-supported controls", () => {
  for (const profile of ["guide", "math", "language", "compact", "research"]) {
    const explanation = explanationFixtures[profile]
    const html = render(ExplanationCard, { explanation, readOnly: true })
    assert.match(html, new RegExp(`data-explanation-card="${profile}"`))
    assert.equal(html.includes("Checklist progress"), profile === "guide")
    assert.equal(html.includes("Show answer"), profile === "language")
    assert.equal(html.includes("Expand all"), ["guide", "language", "research"].includes(profile))
    assert.doesNotMatch(html, /Save to Library|Save to Notebook|Discuss in Socratic dialogue/)
  }
  const guide = render(ExplanationCard, { explanation: explanationFixtures.guide })
  inOrder(guide, "Explanation incomplete", "Screenshot 2", "Appendix A", "Part 1", "Run in PowerShell", "Expected result", "Troubleshooting", "Part 2", "Deliverables")
  assert.doesNotMatch(guide, /screenshot:2|appendix:A/)
  assert.ok(guide.includes(python.replaceAll('"', "&quot;")))
  const math = render(ExplanationCard, { explanation: explanationFixtures.math })
  inOrder(math, "Formula", "katex", "Derivation", "Equation", "Reason", "Worked example", "Verification")
  const research = render(ExplanationCard, { explanation: explanationFixtures.research })
  inOrder(research, "Research question", "Methodology", "Key findings", "Supporting evidence", "<table", "Interpretation", "Limitations")
})

test("unknown sections, language-specific notices and older source shapes degrade safely", () => {
  const { research, compact } = explanationFixtures
  const generic = {
    ...compact, definition: "# Topic with **emphasis**\n\nA legacy explanation.",
    sections: Array.from({ length: 5 }, (_, index) => ({
      heading: `Custom heading ${index + 1}`, content: "Unstructured prose about the same theme.",
    })),
    citations: [...research.citations, { ...research.citations[0], excerpt: "" },
      { ...research.citations[0], page_number: -1, filename: "Invalid.pdf", document_id: "invalid" }],
  }
  const layout = explanationCardLayout(generic)
  assert.equal(layout.profile, "generic")
  assert.equal(layout.citations.length, 3)
  const html = render(ExplanationCard, { explanation: generic, readOnly: true })
  assert.match(html, /Topic with <strong>emphasis<\/strong>/)
  assert.match(html, /Custom heading 5/)
  assert.doesNotMatch(html, /page=-1|view\/invalid/)
  assert.deepEqual(coverageCopy("Vérification de la couverture", "Éléments insuffisamment couverts. (1): screenshot:2 (p. 7)."), {
    summary: "Explication incomplète", detail: "Éléments insuffisamment couverts. (1): Capture 2 (p. 7).",
  })
  assert.match(coverageCopy("شرح غير مكتمل", "question:6").detail, /السؤال 6/)
  assert.equal(coverageCopy("Part 1 of 2", "More content follows.").summary, "Part 1 of 2")
  assert.doesNotMatch(coverageCopy("Coverage check", "installation:4c03d5c797d69869 (p. 2).").detail, /4c03d5c797d69869/)
})

test("task progress is isolated by owner and explanation, and stores only booleans and numeric positions", () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "window")
  const storage = new Map()
  Object.defineProperty(globalThis, "window", { configurable: true, value: { localStorage: {
    getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value),
  } } })
  try {
    const key = explanationProgressKey("owner-a", "message-a")
    writeExplanationProgress(key, { 0: false, 1: true, 6: true })
    assert.deepEqual(readExplanationProgress(key, 2), { 0: false, 1: true })
    assert.deepEqual(readExplanationProgress(explanationProgressKey("owner-b", "message-a"), 2), {})
    assert.deepEqual(readExplanationProgress(explanationProgressKey("owner-a", "message-b"), 2), {})
    storage.set(key, "invalid")
    assert.deepEqual(readExplanationProgress(key, 2), {})
    delete globalThis.window
    assert.doesNotThrow(() => writeExplanationProgress(key, { 0: true }))
    assert.deepEqual(readExplanationProgress(key, 2), {})
  } finally {
    if (original) Object.defineProperty(globalThis, "window", original)
    else delete globalThis.window
  }
})

test("PowerShell line breaks and intentional continuation are preserved across card and capture", () => {
  const commands = ["$root = 'lab'; Set-Location $root", "python -m pip install " + String.fromCharCode(96), "    numpy pandas", "python .\\rows.py"]
  const content = "~~~powershell\r\n" + commands.join("\r\n") + "\r\n~~~"
  const explanation = { ...explanationFixtures.guide, sections: [{ heading: "Step 1", content }] }
  const html = render(ExplanationCard, { explanation, readOnly: true })
  const displayed = html.match(/<pre[^>]*><code>([\s\S]*?)<\/code><\/pre>/)?.[1].replaceAll("&#x27;", "'")
  assert.equal(displayed, commands.join("\r\n"))
  assert.ok(explanationNoteText(explanation).includes(content))
})

test("workflow mappings in fences, code fields and walkthroughs render as readable text", () => {
  const mapping = "pd.read_csv(...) -> File (Orange) -> CSV Reader (KNIME)"
  const labels = "File\nCSV Reader"
  const explanation = { ...card, sections: [
    { heading: "Workflow equivalents", content: "~~~text\n" + mapping + "\n~~~", code: labels,
      code_language: "text", walkthrough: [{ code: "Table Reader\nData Table", explanation: "Shows the imported rows." }]
    },
    { heading: "Real commands", content: "~~~text\npython -m pip install pandas\n~~~\n\n~~~powershell\nWrite-Output ready\n~~~\n\n~~~text\nGit Status\nGit Diff\n~~~" },
  ] }
  const html = render(ExplanationCard, { explanation, readOnly: true })
  inOrder(html, "pd.read_csv(...)", "File (Orange)", "CSV Reader (KNIME)", "CSV Reader", "Table Reader", "Data Table", "Shows the imported rows.", "python -m pip install pandas", "Run in PowerShell", "Write-Output ready")
  assert.equal(html.match(/Copy code/g)?.length, 2)
  assert.doesNotMatch(render(StudyMarkdown, { content: "~~~text\n" + mapping + "\n~~~" }), /Copy code/)
})

test("a final explanation keeps the question and its dialogue action in one unit", () => {
  const question = "Why compare outcomes from the same test split?"
  const TutorMessage = load("components/chat/TutorMessage.tsx").TutorMessage
  const { Message } = load("components/chat/Message.tsx", { "./TutorMessage": { TutorMessage },
    "./StudentMessage": { StudentMessage: () => null } })
  const explanation = { ...explanationFixtures.guide, check_question: question }
  const preview = { role: "assistant", parts: [{ type: "text", text: question }], metadata: { explanationPreview: true } }
  const final = { ...preview, metadata: { ...preview.metadata, explanation } }
  const html = render(Message, { message: final, isStreaming: true }) +
    render(ExplanationCard, { explanation, onDiscuss: () => {} })
  assert.equal(html.split(question).length - 1, 1)
  assert.equal(html.match(/Discuss in Socratic dialogue/g)?.length, 1)
  assert.match(html, /<section[^>]+>[^]*Check your understanding[^]*Why compare outcomes[^]*Discuss in Socratic dialogue[^]*<\/section>/)
})

test("adaptive French cards render lists, revision sections and separate progress states", () => {
  const base = { ...card, language: "French", definition: "", intuition: "", course_example: "", check_question: "" }
  const summary = render(ExplanationCard, { explanation: { ...base, presentation: "brief",
    sections: [{ heading: "Résumé du cours", content: "La prédiction peut être expliquée.\n\n- Mesurer le score\n- Vérifier la source" }],
  } })
  assert.match(summary, /<ul[^>]*>/)
  const revision = render(ExplanationCard, { explanation: { ...base, presentation: "revision_sheet",
    sections: [{ heading: "Définitions", content: "Un modèle simplifie une situation." },
      { heading: "Questions de révision", content: "1. Que simplifie le modèle ?" }],
  } })
  inOrder(revision, "Fiche de révision", "Définitions", "Questions de révision")
  const course = { part: 1, total_parts: 2, request_id: "first", next_request_id: "second",
    language: "French", inventory_uncertain: true, sections: [
      { id: "a", title: "Prédiction", start: 1, end: 2, part: 1, status: "partial" },
      { id: "b", title: "Audit", start: 3, end: 4, part: 2, status: "not_yet_generated" },
    ] }
  const whole = render(ExplanationCard, { explanation: { ...base, presentation: "full_course", course_progress: course },
    onContinueCourse() {},
  })
  inOrder(whole, "Partie 1 sur 2", "Prédiction", "Partiel", "Audit", "À venir", "Continuer avec la partie 2")
})

test("brief output uses the compact card, keeping only extra pages and excerpts in its footer", () => {
  const supplemental = { ...citation, page_number: 15, excerpt: "A different source page remains reachable." }
  const explanation = { ...explanationFixtures.compact, definition: "", sections: [{
    heading: "Summary", content: "Compare held-out metrics.\n\n- Use the same split.\n- Keep the target consistent.", citations: [citation],
  }], citations: [citation, supplemental] }
  const html = render(ExplanationCard, { explanation, onSaveToLibrary: () => {}, notebookCapture: { onClick: () => {} } })
  assert.match(html, /data-explanation-card="compact"/)
  assert.equal(html.match(/>Summary<\/h3>/g)?.length, 1)
  assert.doesNotMatch(html, />Summary<\/h4>/)
  assert.match(html, /<header[^>]*>[^]*Save to Library[^]*Save to Notebook[^]*<\/header>/)
  assert.equal(html.match(/\?page=9#page=9/g)?.length, 1)
  assert.equal(html.match(/\?page=15#page=15/g)?.length, 1)
  assert.equal(html.match(/Capture the finished settings panel/g)?.length, 1)
  assert.match(html, /A different source page remains reachable/)
  assert.doesNotMatch(html, /Check your understanding|Common pitfalls|From your course|Copy code/)
})

test("the scroll shortcut sits outside the message viewport directly before the composer", () => {
  const nothing = () => null
  const { ChatPanel } = load("components/chat/ChatPanel.tsx", {
    react: { ...React, useState: () => [true, () => {}] },
    "./MessageList": { MessageList: () => React.createElement("p", null, "Message viewport") },
    "./ChatInput": { ChatInput: () => React.createElement("textarea", { "aria-label": "Chat composer" }) },
    "./ExerciseCard": { ExerciseCard: nothing },
    "./ExerciseFeedbackCard": { ExerciseFeedbackCard: nothing },
    "./ExplanationCard": { ExplanationCard: nothing },
    "@/components/ui/select": { Select: nothing, SelectContent: nothing, SelectItem: nothing, SelectTrigger: nothing, SelectValue: nothing },
    "@/components/ui/button": { Button: ({ children, "aria-label": label, "aria-controls": controls }) =>
      React.createElement("button", { "aria-label": label, "aria-controls": controls }, children) },
  })
  const html = render(ChatPanel, { messages: [], learningMode: "explain", status: "ready" })
  const viewportId = html.match(/id="([^"]+)" role="region" aria-label="Chat messages"/)?.[1]
  assert.ok(viewportId)
  inOrder(html, "Message viewport</p></div></div>", 'aria-label="Scroll to latest message"', 'aria-label="Chat composer"')
  assert.ok(html.includes('aria-controls="' + viewportId + '"'))
})

test("Notebook table fallback retains row boundaries through editor rendering and text export", () => {
  const table = "| Model | F1 |\n| --- | --- |\n| Learner A | 0.781 |\n| Learner B | 0.837 |"
  const explanation = { ...explanationFixtures.guide, sections: [{ heading: "Evaluation", content: table }] }
  assert.match(render(ExplanationCard, { explanation, readOnly: true }), /<table/)
  assert.match(render(StudyMarkdown, { content: table }), /<table/)
  const note = readNoteDocument(null, explanationNoteText(explanation), true)
  const stored = readNoteDocument(JSON.parse(JSON.stringify(note)), "")
  const tableBlock = stored.content.find((node) => noteText(node) === table)
  assert.equal(tableBlock.content.filter((node) => node.type === "hardBreak").length, 3)
  assert.ok(noteText(stored).includes(table))
})

test("source results and labeled general guidance stay near the step and plain quotes remain unchanged", () => {
  const content = [
    "Open the Scorer.",
    "> **You should see:** The reference F1 is 0.837.",
    "> **Tip (general guidance):** Keep your observations in a separate column.",
    "> An ordinary quote.",
  ].join("\n\n")
  const explanation = { ...explanationFixtures.guide, sections: [
    { heading: "Step 1", content, citations: [citation] },
    { heading: "Expected results", content: "Inspect the run's reported F1." },
  ] }
  const html = render(ExplanationCard, { explanation, readOnly: true })
  inOrder(html, "?page=9#page=9", "Open the Scorer.", "You should see:", "0.837", "Tip (general guidance):", "An ordinary quote.")
  assert.equal(html.match(/<blockquote/g)?.length, 3)
  const note = explanationNoteText(explanation)
  assert.ok(note.includes("> An ordinary quote."))
  assert.doesNotMatch(note, /> Source reference/)
  assert.match(explanationNoteText(card), /> Source reference/)
})
