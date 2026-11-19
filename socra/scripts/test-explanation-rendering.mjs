import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"
import { explanationFixtures, python } from "./explanation-card-fixtures.mjs"

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
const { TutorMessage } = load("components/chat/TutorMessage.tsx")
const { coverageCopy, explanationCardLayout } = load("lib/ai/explanation-card-layout.ts")
const { explanationProgressKey, readExplanationProgress, writeExplanationProgress } = load("lib/ai/explanation-progress.ts")
const { StudyMarkdown, NotebookReply } = load("components/notebook/NotebookReply.tsx")
const { explanationNoteText } = load("lib/ai/explanation-note.ts")
const { readNoteDocument, noteText } = load("lib/notebook/document.ts")
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props))

test("Ask Socra replies offer append only when complete", () => {
  const props = { content: "A worked example. ".repeat(120), onInsertAtEnd: () => {} }
  inOrder(render(NotebookReply, { ...props, streaming: false }), "Copy response", "Insert at end", "Collapse response")
  assert.doesNotMatch(render(NotebookReply, { ...props, streaming: true }), /Insert at end/)
  assert.doesNotMatch(render(NotebookReply, { ...props, streaming: false, partial: true }), /Insert at end/)
})

test("brief metadata preserves a compact table and source order, and keeps extras optional", () => {
  const html = render(ExplanationCard, { explanation: explanationFixtures.brief, onDiscuss: () => {} })
  inOrder(html, "The exercise compares", "<table", "Copy as Markdown", "?page=2#page=2", "?page=7#page=7")
  assert.match(html, /data-explanation-card="compact"/)
  assert.match(html, /<details[^>]+>\s*<summary[^>]+>Common pitfalls/)
  assert.doesNotMatch(html, /Expand all|<progress/)
})

test("standard sourced measurements stay in a table without walkthrough controls", () => {
  const html = render(ExplanationCard, { explanation: explanationFixtures.standard })
  inOrder(html, "Why normalize", "Scaling makes distances", "<ol", "Expected results", "<table", "0.478", "0.780")
  assert.doesNotMatch(html, /Expand all|<progress/)
})

test("focused reports show navigable headings and save the introduction as prose", () => {
  const explanation = {
    ...explanationFixtures.standard,
    definition: "# Transformer et Estimator\n\nLes deux interviennent à des étapes différentes.",
    intuition: "",
    language: "French",
    sections: [
      { heading: "Transformer", content: "Applique une transformation.", citations: [] },
      { heading: "Estimator", content: "Ajuste un modèle.", citations: [] },
      { heading: "Exemple de pipeline", content: "Un modèle ajusté peut transformer de nouvelles données.", citations: [] },
    ],
  }
  const html = render(ExplanationCard, { explanation })
  assert.match(html, /<nav aria-label="Dans cette explication"/)
  const targets = [...html.matchAll(/href="#([^"]+-section-\d+)"/g)].map((match) => match[1])
  assert.equal(targets.length, 3)
  for (const target of targets) assert.ok(html.includes(`<section id="${target}"`))
  assert.match(html, /<h4[^>]*>Exemple de pipeline<\/h4>/)
  assert.match(explanationNoteText(explanation), /^# Transformer et Estimator\n\nLes deux interviennent/)
  assert.match(html, /class="explanation-document /)
  const streamed = render(TutorMessage, { content: explanationNoteText(explanation), explanationPreview: true, isStreaming: true })
  assert.match(streamed, /class="explanation-document /)
  assert.match(streamed, /<h3[^>]*>Transformer et Estimator<\/h3>/)
  assert.match(streamed, /Responding/)
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
    assert.equal(html.includes("Expand all"), profile === "guide")
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
    "./ExplainPdfSelect": { ExplainPdfSelect: nothing },
    "@/components/ui/select": { Select: nothing, SelectContent: nothing, SelectItem: nothing, SelectTrigger: nothing, SelectValue: nothing },
    "@/components/ui/button": { Button: ({ children, "aria-label": label, "aria-controls": controls }) =>
      React.createElement("button", { "aria-label": label, "aria-controls": controls }, children) },
  })
  const props = { messages: [], learningMode: "explain", status: "ready" }
  const html = render(ChatPanel, { ...props, contextOpen: false })
  assert.match(html, /data-course-context="closed"/)
  assert.match(render(ChatPanel, { ...props, contextOpen: true }), /data-course-context="open"/)
  const viewportId = html.match(/id="([^"]+)" role="region" aria-label="Chat messages"/)?.[1]
  assert.ok(viewportId)
  inOrder(html, "Message viewport</p></div></div>", 'aria-label="Scroll to latest message"', 'aria-label="Chat composer"')
  assert.ok(html.includes('aria-controls="' + viewportId + '"'))
})

test("Notebook native tables retain row boundaries through editor rendering and text export", () => {
  const table = "| Model | F1 |\n| --- | --- |\n| Learner A | 0.781 |\n| Learner B | 0.837 |"
  const explanation = { ...explanationFixtures.guide, sections: [{ heading: "Evaluation", content: table }] }
  assert.match(render(ExplanationCard, { explanation, readOnly: true }), /<table/)
  assert.match(render(StudyMarkdown, { content: table }), /<table/)
  const note = readNoteDocument(null, explanationNoteText(explanation), true)
  const stored = readNoteDocument(JSON.parse(JSON.stringify(note)), "")
  const tableBlock = stored.content.find((node) => node.type === "table")
  assert.deepEqual(tableBlock.content.map((row) => row.content.map(noteText)), [
    ["Model", "F1"], ["Learner A", "0.781"], ["Learner B", "0.837"],
  ])
  assert.ok(noteText(stored).includes("Learner A\t0.781\nLearner B\t0.837"))
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
