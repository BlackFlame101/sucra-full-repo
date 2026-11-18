import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { existsSync, readFileSync, writeFileSync } from "node:fs"
import { createRequire, isBuiltin } from "node:module"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

const root = fileURLToPath(new URL("../", import.meta.url))
const require = createRequire(import.meta.url)
const memo = new Map()
const compilerOptions = { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }
function localFile(request, containing) {
  const base = request.startsWith("@/") ? join(root, request.slice(2)) : resolve(dirname(containing), request)
  return [base, base + ".ts", base + ".tsx"].find((path) => /\.(ts|tsx)$/.test(path) && existsSync(path))
}
function load(path) {
  if (!memo.has(path)) {
    const exports = {}
    const output = ts.transpileModule(readFileSync(path, "utf8"), { compilerOptions }).outputText
    new Function("exports", "require", output)(exports, (name) => {
      const local = localFile(name, path)
      return local ? load(local) : require(name)
    })
    memo.set(path, exports)
  }
  return memo.get(path)
}
const app = (name) => load(join(root, name))
const fixture = {
  schema_version: 3, format: "educational_document", document_id: "a".repeat(24),
  revision_id: "b".repeat(24), state: "approved", title: "Étudier une classification", summary: "",
  intent: { action: "solve", language: "French" },
  source: { document_id: "280de0bf-9b17-4192-8c94-ee07cbef18b6", filename: "TP4_Spark_MLlib.pdf", source_hash: "c".repeat(64), index_generation: 2 },
  citations: [{ citation_id: "d".repeat(24), span: { page: 2, start: 10, end: 47 }, quote: "Source", checksum: "e".repeat(64) }],
  prerequisites: [], remaining: [], code_cells: [{ cell_id: "f".repeat(24) }], sections: [],
}
const intro = "# Étudier une classification\n\n"
const heading = "## 🧪 Préparer et contrôler les données\n\n"
const second = "## Vérifier les métriques\n\n"
const body = "Le document lie chaque observation à un résultat attendu. [[" + fixture.citations[0].citation_id + "]]\n\n" +
  "| Mesure | Interprétation |\n| --- | --- |\n| F1 | Compromis entre précision et rappel. |\n\n" +
  "$$F_1 = 2\\frac{PR}{P+R}$$\n\n~~~python cell:" + fixture.code_cells[0].cell_id + "\n" +
  "def mesure(score):\n    return score\n\nprint(mesure(1))\n~~~\n\n"
fixture.document_markdown = intro + heading + body + second + "Mesurer uniquement après avoir choisi le modèle.\n"
fixture.sections = [
  { section_id: "1".repeat(24), markdown_start: Array.from(intro).length },
  { section_id: "2".repeat(24), markdown_start: Array.from(intro + heading + body).length },
]
const { EducationalDocumentCard } = app("components/chat/EducationalDocumentCard.tsx")
const { educationalNote, noteText, readNoteDocument } = app("lib/notebook/document.ts")
const { validateNoteDocument, notebookExtensions } = app("lib/notebook/schema.ts")
const { notebookPrintHtml } = app("lib/notebook/print.ts")

function descendants(node, kind) {
  return [...(node.type === kind ? [node] : []), ...(node.content ?? []).flatMap((child) => descendants(child, kind))]
}

test("document snapshots and Card preserve one identity, complete code and versioned citations", () => {
  const { parseServerMessage } = app("lib/socra-ws.ts")
  assert.equal(parseServerMessage(JSON.stringify({ type: "document_snapshot", content: { ...fixture, state: "partial" } })).content.document_id, fixture.document_id)
  assert.equal(parseServerMessage(JSON.stringify({ type: "document_snapshot", content: { schema_version: 3 } })), null)
  const html = renderToStaticMarkup(React.createElement(EducationalDocumentCard, { document: fixture }))
  assert.equal((html.match(/<h1/g) ?? []).length, 1)
  assert.match(html, /data-code-cell="ffffffffffffffffffffffff"/)
  assert.match(html, /p\. 2/)
  assert.match(html, /source=cccc/)
  assert.match(html, /<table/)
  assert.match(html, /<math/)
  assert.match(html, /return score/)
})

test("interrupted educational documents show a public status and preserve their partial content", () => {
  const render = (state, finding) => renderToStaticMarkup(React.createElement(EducationalDocumentCard, {
    document: { ...fixture, state, verification: { findings: [finding] } },
  }))
  const generation = render("partial", "generate_transport_exhausted")
  assert.match(generation, /Génération temporairement indisponible\. Document incomplet\./)
  assert.match(generation, /return score/)
  assert.doesNotMatch(generation, /generate_transport_exhausted/)
  assert.match(render("review_pending", "review_provider_unavailable"), /Vérification temporairement indisponible/)
  assert.doesNotMatch(render("approved", "generate_transport_exhausted"), /Document incomplet/)
})

test("the same canonical content round-trips through the editable Notebook schema", () => {
  const note = validateNoteDocument(educationalNote(fixture))
  const serialized = JSON.stringify(note)
  const reopened = validateNoteDocument(readNoteDocument(JSON.parse(serialized), "legacy fallback"))
  assert.deepEqual(reopened, note)
  assert.deepEqual(descendants(reopened, "heading").slice(1).map((n) => n.attrs.sectionId), fixture.sections.map((r) => r.section_id))
  assert.equal(descendants(reopened, "table").length, 1)
  const [cell] = descendants(reopened, "codeBlock")
  assert.equal(cell.attrs.cellId, fixture.code_cells[0].cell_id)
  assert.equal(noteText(cell), "def mesure(score):\n    return score\n\nprint(mesure(1))")
  const [citation] = descendants(reopened, "sourceCitation")
  assert.equal(citation.attrs.checksum, fixture.citations[0].checksum)
  assert.equal(descendants(reopened, "blockMath")[0].attrs.latex, "F_1 = 2\\frac{PR}{P+R}")
  // Simulate a user edit through ProseMirror and reopen exactly that version.
  const { getSchema } = require("@tiptap/core")
  const { EditorState } = require("@tiptap/pm/state")
  const schema = getSchema(notebookExtensions)
  const state = EditorState.create({ doc: schema.nodeFromJSON(note) })
  let position = 0
  state.doc.descendants((node, pos) => {
    if (node.type.name === "tableCell" && !position) position = pos + 2
  })
  const edited = validateNoteDocument(state.apply(state.tr.insertText("Mesure : ", position)).doc.toJSON())
  assert.match(noteText(edited), /Mesure : F1/)
  assert.doesNotMatch(noteText(note), /Mesure : F1/)
  assert.deepEqual(descendants(edited, "sourceCitation"), [citation])
})

test("print view formats the edited document with an outline, tables, equations and complete cells", () => {
  const note = validateNoteDocument(educationalNote(fixture))
  const html = notebookPrintHtml(fixture.title, note, { french: true })
  assert.match(html, /<nav><h2>Sommaire/)
  assert.match(html, /<thead>/)
  assert.match(html, /<math/)
  assert.match(html, /counter\(page\)/)
  assert.match(html, /break-after:avoid/)
  assert.match(html, /def mesure\(score\):\n    return score/)
  assert.equal((html.match(/<h1>/g) ?? []).length, 1)
})

async function productionCss() {
  const postcss = require("postcss")
  const tailwind = require("@tailwindcss/postcss")
  const file = join(root, "app/globals.css")
  return (await postcss([tailwind({ base: root, optimize: false })])
    .process(readFileSync(file, "utf8"), { from: file })).css
}

// Package the actual Notebook extensions and Tiptap editor into an offline
// browser fixture. The test host never makes authenticated or network requests.
function editorBundle() {
  const entries = []
  const seen = new Map()
  function add(file) {
    if (seen.has(file)) return seen.get(file)
    const id = entries.length
    seen.set(file, id)
    entries.push(null)
    const input = readFileSync(file, "utf8")
    const needsTranspile = /\.(ts|tsx|mjs)$/.test(file) || /^\s*(?:import|export)(?:\s|[{*])/m.test(input)
    const matches = needsTranspile ? ts.transpileModule(input, { compilerOptions }).outputText
      : file.endsWith(".json") ? "module.exports = " + input : input
    const deps = {}
    for (const match of matches.matchAll(/\brequire\(["']([^"']+)["']\)/g)) {
      const name = match[1]
      if (isBuiltin(name) || name in deps) continue
      const dependency = localFile(name, file) ?? createRequire(file).resolve(name)
      deps[name] = add(name === "marked" ? join(dirname(dependency), "marked.umd.js") : dependency)
    }
    entries[id] = [matches, deps, file.slice(root.length)]
    return id
  }
  const schema = add(join(root, "lib/notebook/schema.ts"))
  const editor = add(require.resolve("@tiptap/core"))
  const wire = JSON.stringify(entries).replaceAll("</script", "<\\/script")
  return { wire, schema, editor }
}

test("offline browser can render the Card, edit the Notebook fixture and print a PDF", {
  skip: !(process.env.SOCRA_PHASE7_OUTPUT_DIR && process.env.SOCRA_TEST_BROWSER && process.env.SOCRA_PHASE7_FIXTURE),
}, async () => {
  const output = process.env.SOCRA_PHASE7_OUTPUT_DIR
  const spark = JSON.parse(readFileSync(process.env.SOCRA_PHASE7_FIXTURE, "utf8"))
  const note = validateNoteDocument(educationalNote(spark))
  assert.deepEqual(descendants(note, "codeBlock").map((cell) => [cell.attrs.cellId, noteText(cell)]),
    spark.code_cells.map((cell) => [cell.cell_id, cell.code]))
  assert.equal(descendants(note, "heading").filter((row) => row.attrs.sectionId).length, spark.sections.length)
  const css = await productionCss()
  const card = renderToStaticMarkup(React.createElement(EducationalDocumentCard, { document: spark,
    onSaveToLibrary: () => {}, notebookCapture: { onClick: () => {} } }))
  assert.deepEqual(Array.from(card.matchAll(/data-code-cell="([a-f0-9]{24})"/g), (match) => match[1]),
    spark.code_cells.map((cell) => cell.cell_id))
  const head = '<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>' +
    css + "</style>"
  const cardFile = join(output, "phase7-card-preview.html")
  const mobileFile = join(output, "phase7-card-mobile-preview.html")
  const noteFile = join(output, "phase7-notebook-preview.html")
  const printFile = join(output, "phase7-notebook-print.html")
  const stressPrintFile = join(output, "phase7-notebook-print-stress.html")
  const printExtra = educationalNote(fixture)
  const printCombined = { ...note, content: [...note.content, ...printExtra.content.slice(1)] }
  writeFileSync(cardFile, head + '<body><main class="mx-auto max-w-4xl">' + card + "</main></body></html>")
  // Desktop Chromium enforces a minimum outer window width. Its iframe still
  // has a 390 px layout viewport, so the Card uses the mobile media queries.
  writeFileSync(mobileFile, '<!doctype html><meta charset="utf-8"><body style="margin:0;overflow:hidden">' +
    '<iframe src="phase7-card-preview.html" title="Mobile Explanation Card" width="390" height="844" ' +
    'style="display:block;border:0"></iframe></body>')
  writeFileSync(printFile, notebookPrintHtml(spark.title, note, { french: true }))
  writeFileSync(stressPrintFile, notebookPrintHtml(spark.title, printCombined, { french: true }))

  const bundle = editorBundle()
  const json = JSON.stringify(note).replaceAll("</script", "<\\/script")
  writeFileSync(noteFile, head +
    '<body><main class="mx-auto max-w-[50rem] px-5 py-6"><div class="border-b pb-4 text-sm text-muted-foreground">Notebook · Document généré</div>' +
    '<div id="editor"></div><output id="result" hidden>pending</output></main><script>' +
    "const modules=" + bundle.wire + ";const cache={};" +
    "function load(id){if(cache[id])return cache[id].exports;const m={exports:{}};cache[id]=m;" +
    "const [code,deps,file]=modules[id];try{new Function('module','exports','require','process',code)(m,m.exports,n=>load(deps[n]),{env:{NODE_ENV:'production'}})}" +
    "catch(error){throw Error(file+': '+error.message)}return m.exports}" +
    "try{const {Editor}=load(" + bundle.editor + ");const {notebookExtensions}=load(" + bundle.schema + ");const input=" + json + ";" +
    "const editor=new Editor({element:document.querySelector('#editor'),extensions:notebookExtensions,content:input,editorProps:{attributes:{class:'notebook-prose'}}});" +
    "const code=editor.getJSON().content.filter(n=>n.type==='codeBlock').length;" +
    "editor.commands.insertContentAt(2,'Test ');const edited=editor.getJSON();if(!JSON.stringify(edited).includes('Test '))throw Error('Editing failed');" +
    "editor.commands.setContent(input);if(editor.getJSON().content.filter(n=>n.type==='codeBlock').length!==code)throw Error('Reopen lost code');" +
    "result.textContent='PASS'}catch(error){result.textContent=error.stack}</script></body></html>")

  function browser(file, flags) {
    const profile = join(output, "phase7-chromium-profile")
    const result = spawnSync(process.env.SOCRA_TEST_BROWSER, ["--headless", "--disable-gpu", "--no-sandbox",
      "--no-proxy-server", "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
      "--user-data-dir=" + profile, "--virtual-time-budget=2500", ...flags, pathToFileURL(file).href],
    { encoding: "utf8", timeout: 45_000, maxBuffer: 16_000_000 })
    assert.equal(result.status, 0, result.error?.message || result.stderr)
    return result.stdout
  }
  const browserNote = browser(noteFile, ["--dump-dom"])
  const verdict = /<output id="result"[^>]*>([\s\S]*?)<\/output>/.exec(browserNote)?.[1]
  assert.equal(verdict?.split("\n")[0].trim(), "PASS", verdict?.slice(0, 800) ?? "Notebook fixture did not initialize")
  browser(cardFile, ["--window-size=1360,1050", "--screenshot=" + join(output, "phase7-card-desktop.png")])
  browser(mobileFile, ["--window-size=390,844", "--screenshot=" + join(output, "phase7-card-mobile.png")])
  browser(noteFile, ["--window-size=1360,1050", "--screenshot=" + join(output, "phase7-notebook-desktop.png")])
  const pdf = join(output, "phase7-notebook.pdf")
  browser(printFile, ["--no-pdf-header-footer", "--print-to-pdf=" + pdf])
  assert.equal(readFileSync(pdf).subarray(0, 5).toString(), "%PDF-")
  const stressPdf = join(output, "phase7-notebook-print-stress.pdf")
  browser(stressPrintFile, ["--no-pdf-header-footer", "--print-to-pdf=" + stressPdf])
  assert.equal(readFileSync(stressPdf).subarray(0, 5).toString(), "%PDF-")
})
