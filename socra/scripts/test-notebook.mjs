import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import test from "node:test"
import ts from "typescript"
import { getDocumentProxy } from "unpdf"

const require = createRequire(import.meta.url)
function load(path, dependencies = {}) {
  const source = readFileSync(new URL(`../${path}`, import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  })
  const exports = {}
  new Function("exports", "require", outputText)(exports, (name) => dependencies[name] ?? require(name))
  return exports
}

const document = load("lib/notebook/document.ts")
const schema = load("lib/notebook/schema.ts", { "./document": document })
const id = "00000000-0000-0000-0000-000000000001"
const course = "00000000-0000-0000-0000-000000000002"
const session = "00000000-0000-0000-0000-000000000003"

test("study routes authorize the note before opening inquiries or reading cards", async () => {
  let viewer = null
  let ownsNote = false
  let serviceCalls = 0
  const deniedOrOwned = {
    auth: { getUser: async () => ({ data: { user: viewer } }) },
    from: () => query((fields) => ownsNote && fields.user_id === "owner" && fields.id === id
      ? { id, version: 3 } : null),
  }
  const { GET, POST, PATCH } = load("app/api/notebook/[id]/study/route.ts", {
    "next/server": { NextResponse: Response },
    "@/lib/notebook/schema": schema,
    "@/lib/supabase/server": { createClient: async () => deniedOrOwned, createServiceClient: async () => {
      serviceCalls++
      return {
        from: (table) => query((fields) => table === "notebook_flashcards" && fields.note_id === id
          ? { note_version: 2, cards: [{ question: "Why?", answer: "Because." }] }
          : fields.id === id && fields.user_id === "owner" ? { review_due: null } : null),
        rpc: async (_name, args) => {
          assert.deepEqual(args, { owner: "owner", note: id })
          return { data: { sessionId: session } }
        },
      }
    } },
  })
  const params = { params: Promise.resolve({ id }) }
  const url = "https://socra.test/notebook/study"
  assert.equal((await GET(new Request(url), params)).status, 401)
  viewer = { id: "owner" }
  assert.equal((await POST(new Request(url), params)).status, 404)
  assert.equal(serviceCalls, 0)
  ownsNote = true
  assert.equal((await (await GET(new Request(url), params)).json()).stale, true)
  assert.equal((await (await POST(new Request(url), params)).json()).sessionId, session)
  const review = (review_due) => PATCH(new Request(url, { method: "PATCH", body: JSON.stringify({ review_due }) }), params)
  assert.equal((await review("2026-02-30")).status, 400)
  assert.equal((await review(null)).status, 200)
})

test("legacy text is preserved and markdown captures round-trip in the Tiptap schema", () => {
  assert.equal(document.noteText(document.readNoteDocument(null, "# Plain title\n\nLine 3")), "# Plain title\n\nLine 3")
  const text = "# Heading\n\nA **bold** and *italic* example with $x^2$.\n\n- [x] Task\n\n> Quote\n\n~~~python\nprint(42)\n~~~\n\n$$x + y = 2$$"
  const doc = schema.validateNoteDocument(document.markdownNote(text))
  assert.deepEqual(doc.content.map((node) => node.type), ["heading", "paragraph", "taskList", "blockquote", "codeBlock", "blockMath"])
  assert.match(document.noteText(doc), /x\^2/)
  assert.equal(doc.content[4].attrs.language, "python")
  assert.equal(document.selectNoteText(doc, "bold")[0].content[0].marks[0].type, "bold")
  assert.equal(document.selectNoteText(doc, "print(42)")[0].type, "codeBlock")
  assert.equal(document.selectNoteText(doc, "invented text"), null)
  assert.throws(() => schema.validateNoteDocument({ type: "doc", content: [{ type: "paragraph", content: [
    { type: "text", text: "unsafe", marks: [{ type: "link", attrs: { href: "javascript:alert(1)" } }] },
  ] }] }), /valid HTTPS/)
})

test("legacy Markdown imports keep lists, headings, code and citation links", () => {
  const legacy = "# Study notes\n\n* Item one\n* Item two\n\n~~~python\nprint('* literal')\n~~~\n\n[PDF · page 3](/api/documents/view/example?page=3#page=3)"
  const doc = schema.validateNoteDocument(document.readNoteDocument(null, legacy))
  assert.deepEqual(doc.content.map(({ type }) => type), ["heading", "bulletList", "codeBlock", "paragraph"])
  assert.equal(doc.content[2].content[0].text, "print('* literal')")
  assert.match(doc.content[3].content[0].marks[0].attrs.href, /#page=3$/)
  assert.equal(document.readNoteDocument(document.emptyNote, legacy), document.emptyNote)
  assert.equal(document.noteText(document.readNoteDocument(null, "x * y")), "x * y")
})

test("AI Markdown envelopes are removed without stripping literal code or equations", () => {
  const doc = schema.validateNoteDocument(document.suggestionNote("~~~~markdown\n## Suggested\n\n* One\n* Two\n\n~~~js\nconst x = a * b\n~~~\n\n$$x^2$$\n~~~~"))
  assert.deepEqual(doc.content.map(({ type }) => type), ["heading", "bulletList", "codeBlock", "blockMath"])
  assert.equal(doc.content[2].content[0].text, "const x = a * b")
  assert.equal(document.suggestionNote("~~~js\nx * y\n~~~").content[0].type, "codeBlock")
})

test("AI edit placement uses the captured range and rejects stale selections", () => {
  const { editRange } = load("lib/notebook/edit-range.ts")
  const pm = require("@tiptap/core").getSchema(schema.notebookExtensions)
  const original = pm.nodeFromJSON(document.markdownNote("Before target after"))
  const updated = pm.nodeFromJSON(document.markdownNote("New text before target after"))
  const anchor = { from: 8, to: 14, text: "target", document: original }
  assert.equal(original.textBetween(anchor.from, anchor.to), "target")
  assert.deepEqual(editRange(original, "replace", anchor), { from: 8, to: 14 })
  assert.equal(editRange(original, "below", anchor), original.content.size)
  assert.equal(editRange(updated, "replace", anchor), null)
  assert.equal(editRange(updated, "below", anchor), null)
  assert.equal(editRange(updated, "end", anchor), updated.content.size)
})

test("note search checks content, tags and course and groups by date", () => {
  const { searchNotes, groupNotes } = load("lib/notebook/notes.ts")
  const note = { title: "Training", content: "Gradient update", topic: "", tags: ["Exam"], starred: true,
    course_id: course, updated_at: new Date(2026, 10, 13, 19).toISOString() }
  assert.deepEqual(searchNotes([note], [{ id: course, name: "Machine learning" }], "Gradient exam machine", "Starred"), [note])
  assert.deepEqual(searchNotes([note], [], "Gradient", "Personal"), [])
  assert.deepEqual(groupNotes([note], new Date(2026, 10, 14))[1], ["This Week", [note]])
})

function query(result, record) {
  const fields = {}
  const builder = {
    select: () => builder,
    eq: (key, value) => { fields[key] = value; return builder },
    limit: () => builder,
    update: (value) => { record?.(value); return builder },
    maybeSingle: async () => ({ data: result(fields), error: null }),
  }
  return builder
}

test("stale autosaves return the owned current version and never overwrite it", async () => {
  const current = { id, user_id: "owner", version: 4, title: "Newer title" }
  let update
  let reads = 0
  const user = {
    auth: { getUser: async () => ({ data: { user: { id: "owner" } } }) },
    from: (table) => query((fields) => {
      assert.equal(fields.user_id, "owner")
      if (table === "courses") return null
      reads++
      return current
    }),
  }
  const { PATCH } = load("app/api/notebook/[id]/route.ts", {
    "next/server": { NextResponse: Response },
    "@/lib/notebook/schema": schema,
    "@/lib/server/notebook": load("lib/server/notebook.ts", { "@/lib/notebook/document": document, "@/lib/notebook/schema": schema }),
    "@/lib/supabase/server": { createClient: async () => user, createServiceClient: async () => ({
      from: () => query((fields) => {
        assert.deepEqual(fields, { id, user_id: "owner", version: 3 })
        return null
      }, (value) => { update = value }),
    }) },
  })
  const save = (payload) => PATCH(new Request("https://socra.test/notebook", {
    method: "PATCH", body: JSON.stringify({ title: "Draft", content_json: document.emptyNote, version: 3, ...payload }),
  }), { params: Promise.resolve({ id }) })
  const conflict = await save()
  assert.equal(conflict.status, 409)
  assert.deepEqual((await conflict.json()).note, current)
  assert.equal(update.version, 4)
  assert.equal((await save({ course_id: course })).status, 404)
  assert.equal(reads, 1)
})

test("capture uses persisted messages and preserves formatting in a selected excerpt", async () => {
  let ownsCourse = false
  let saved
  let correction
  let explanation
  let qcmStatus
  let qcmMarkdown
  let pageCount = 4
  let revealed = false
  let answerReads = 0
  const client = { auth: { getUser: async () => ({ data: { user: { id: "owner" } } }) }, from: (table) => {
    if (table === "sessions") return query((fields) => ownsCourse && fields["courses.user_id"] === "owner" ? { id: session } : null)
    if (table === "documents") return { select: () => ({ eq: (key, value) => {
      assert.deepEqual([key, value], ["course_id", course])
      return { in: async (_column, ids) => {
        assert.ok(ids.includes(id))
        return { data: [{ id, filename: "Course.pdf", page_count: pageCount }] }
      } }
    } }) }
    assert.equal(table, "messages")
    return query((fields) => fields.role === "assistant" && fields.session_id === session
      ? { content: qcmMarkdown ?? "The **verified phrase** is useful.",
          metadata: qcmStatus ? { qcm_status: qcmStatus } : explanation ? { explanation } : correction ? { correction, exercise_id: id } : {} } : null)
  } }
  const { POST } = load("app/api/notebook/capture/route.ts", {
    "next/server": { NextResponse: Response },
    "@/lib/ai/explanation-note": load("lib/ai/explanation-note.ts", {
      "@/lib/ai/explanation-presentation": load("lib/ai/explanation-presentation.ts", {
        "@/lib/notebook/document": document,
      }),
      "@/lib/documents/pdf-page": load("lib/documents/pdf-page.ts"),
    }),
    "@/lib/notebook/document": document, "@/lib/notebook/schema": schema,
    "@/lib/supabase/server": { createClient: async () => client, createServiceClient: async () => ({
      from: (table) => {
        if (table === "exercise_attempts") {
          return query((fields) => {
            assert.equal(fields.user_id, "owner")
            assert.equal(fields.solution_revealed, true)
            return revealed ? { id } : null
          })
        }
        assert.equal(table, "exercises")
        answerReads++
        return query(() => ({ expected_answer: "The private solution", common_mistakes: [] }))
      },
      rpc: async (name, args) => { assert.equal(name, "capture_notebook_response"); saved = args; return { data: { state: "saved", id } } },
    }) },
  })
  const save = (selection) => POST(new Request("https://socra.test/capture", { method: "POST",
    body: JSON.stringify({ course_id: course, session_id: session, message_id: id, request_id: id, selection, content: "Client forgery" }),
  }))
  assert.equal((await save("verified phrase")).status, 404)
  assert.equal(saved, undefined)
  ownsCourse = true
  assert.equal((await save("Client forgery")).status, 422)
  assert.equal(saved, undefined)
  assert.equal((await save("verified phrase")).status, 200)
  assert.equal(saved.body_text, "verified phrase")
  assert.equal(saved.body_nodes[0].content[0].marks[0].type, "bold")
  assert.equal(saved.source_message, id)
  correction = { overall_feedback: "Good reasoning", criterion_feedback: [], next_step: "Practice", citations: [] }
  assert.equal((await save(null)).status, 200)
  assert.equal(answerReads, 0)
  assert.doesNotMatch(saved.body_text, /private solution/)
  revealed = true
  assert.equal((await save(null)).status, 200)
  assert.match(saved.body_text, /The private solution/)

  explanation = {
    definition: "", intuition: "", citations: [],
    sections: [{ heading: "Screenshot checkpoint", content: "Capture the setup.",
      citations: [{ document_id: id, filename: "Old name.pdf", page_number: 4 },
        { document_id: id, filename: "Out of bounds.pdf", page_number: 5 },
        { document_id: session, filename: "Other course.pdf", page_number: 1 }] },
    { heading: "Incomplete explanation", content: "Ask to continue with step 3." }],
  }
  assert.equal((await save(null)).status, 200)
  assert.deepEqual(saved.source_citations, [{ document_id: id, page_number: 4, filename: "Course.pdf" }])
  const note = JSON.stringify(saved.body_nodes)
  assert.match(note, /[?]page=4#page=4/)
  assert.match(note, /Ask to continue with step 3/)
  assert.doesNotMatch(note, /Out of bounds|Other course|[?]page=5/)

  qcmStatus = "unreviewed"
  qcmMarkdown = [
    "# Corrigé proposé · Q1 à Q20", "Réponses du modèle sans corrigé officiel.",
    ...Array.from({ length: 20 }, (_, index) => {
      const number = index + 1
      const page = number <= 5 ? 1 : number <= 11 ? 2 : number <= 17 ? 3 : 4
      return [
        `## Q${number} · [PDF, p. ${page}](/api/documents/view/${id}?page=${page}#page=${page})`,
        `Question originale ${number} sur les compétences ?`,
        [..."ABCD"].map((key) => `- ${key === "A" ? "✓" : "✗"} **${key}. Option ${number}-${key}.**  \n  **Principe** · Développement des compétences.  \n  **Application** · Ce choix s’applique à ${number}-${key}.`).join("\n"),
        "**Choix proposés** · A",
      ].join("\n\n")
    }),
  ].join("\n\n")
  assert.ok(qcmMarkdown.length > 3_000)
  assert.equal((await save(null)).status, 200)
  assert.equal(saved.source_kind, "explanation")
  assert.deepEqual(saved.source_citations.map((citation) => citation.page_number), [1, 2, 3, 4])
  assert.equal(saved.body_nodes.filter((node) => node.type === "heading").length, 21)
  assert.equal(saved.body_nodes.filter((node) => node.type === "bulletList").length, 20)
  assert.equal((saved.body_text.match(/Principe/g) ?? []).length, 80)
  assert.equal((saved.body_text.match(/Application/g) ?? []).length, 80)
  assert.equal((saved.body_text.match(/Choix proposés/g) ?? []).length, 20)
  assert.equal((saved.body_text.match(/✓/g) ?? []).length, 20)
  assert.equal((saved.body_text.match(/✗/g) ?? []).length, 60)
  assert.match(saved.body_text, /Option 20-D\..*\n[\s\S]*20-D\./)
  assert.doesNotMatch(saved.body_text, /Client forgery|Screenshot checkpoint/)
  assert.equal(answerReads, 1)
  const savedQcm = saved
  pageCount = 3
  assert.equal((await save(null)).status, 422)
  assert.equal(saved, savedQcm)
  qcmStatus = "failed"
  assert.equal((await save(null)).status, 422)

  const native = { type: "doc", content: structuredClone(savedQcm.body_nodes) }
  const { editableNote } = load("lib/server/notebook.ts", {
    "@/lib/notebook/document": document, "@/lib/notebook/schema": schema,
  })
  native.content.push({ type: "paragraph", content: [{ type: "text", text: "Ma révision : <script> & vérifiée." }] })
  const fields = editableNote({ title: "Corrigé & révision", content_json: native })
  const persisted = JSON.parse(JSON.stringify({ ...fields, source_type: "explanation" }))
  assert.equal(JSON.stringify(document.readNoteDocument(persisted.content_json, "obsolete legacy text")), JSON.stringify(fields.content_json))

  let requester = "owner"
  const pdfFilename = load("lib/notebook/pdf-filename.ts")
  assert.equal(pdfFilename.notebookPdfFilename("Corrigé & révision"), "Corrigé & révision.pdf")
  assert.equal(pdfFilename.notebookPdfFilename("QCM : Q1/Q20.pdf"), "QCM - Q1-Q20.pdf")
  const { GET } = load("app/api/notebook/[id]/pdf/route.ts", {
    "@/lib/notebook/document": document, "@/lib/notebook/schema": schema,
    "@/lib/notebook/pdf": load("lib/notebook/pdf.ts", { "./document": document }),
    "@/lib/notebook/pdf-filename": pdfFilename,
    "@/lib/supabase/server": { createClient: async () => ({
      auth: { getUser: async () => ({ data: { user: requester ? { id: requester } : null } }) },
      from: (table) => {
        assert.equal(table, "notebook_notes")
        return query((constraints) => constraints.id === id && constraints.user_id === "owner" ? persisted : null)
      },
    }) },
  })
  const download = () => GET(new Request(`https://socra.test/api/notebook/${id}/pdf`), { params: Promise.resolve({ id }) })
  const response = await download()
  assert.equal(response.status, 200)
  assert.equal(response.headers.get("Cache-Control"), "private, no-store")
  assert.equal(response.headers.get("Content-Type"), "application/pdf")
  assert.match(response.headers.get("Content-Disposition"), /Corrig%C3%A9%20%26%20r%C3%A9vision\.pdf/)
  const pdf = await getDocumentProxy(new Uint8Array(await response.arrayBuffer()), { isEvalSupported: false })
  try {
    const text = []
    const links = []
    for (let index = 1; index <= pdf.numPages; index++) {
      const page = await pdf.getPage(index)
      const words = (await page.getTextContent()).items.map((item) => item.str || "").join(" ")
      text.push(words)
      links.push(...(await page.getAnnotations()).map((annotation) => annotation.url))
      assert.ok(words.includes(`${index} / ${pdf.numPages}`))
    }
    const content = text.join(" ")
    assert.equal((content.match(/Question originale/g) ?? []).length, 20)
    assert.equal((content.match(/Principe/g) ?? []).length, 80)
    assert.equal((content.match(/Application/g) ?? []).length, 80)
    assert.equal((content.match(/✓/g) ?? []).length, 20)
    assert.equal((content.match(/✗/g) ?? []).length, 60)
    assert.match(content, /Ma révision : <script> & vérifiée\./)
    assert.ok(links.includes(`https://socra.test/api/documents/view/${id}?page=4#page=4`))
    assert.doesNotMatch(content, /obsolete legacy text/)
  } finally { await pdf.destroy() }
  requester = "other"
  assert.equal((await download()).status, 404)
  requester = null
  assert.equal((await download()).status, 401)
})
