import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import ts from "typescript"

function load(path, dependencies) {
  const source = readFileSync(new URL(`../${path}`, import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  })
  const exports = {}
  new Function("exports", "require", outputText)(exports, (name) => {
    if (!(name in dependencies)) throw new Error(`Unexpected module: ${name}`)
    return dependencies[name]
  })
  return exports
}

test("PDF polling backs off, pauses while hidden and stops at completion", async (t) => {
  const tab = Object.assign(new EventTarget(), { hidden: false })
  const clock = t.mock.timers
  clock.enable({ apis: ["setTimeout"] })
  let cleanup
  const { usePdfPolling } = load("hooks/usePdfPolling.ts", {
    react: { useEffect: (effect) => {
      globalThis.window = { setTimeout, clearTimeout }
      globalThis.document = tab
      cleanup = effect()
    } },
  })
  t.after(() => {
    cleanup?.()
    delete globalThis.window
    delete globalThis.document
  })
  const calls = []
  let resolveRefresh
  usePdfPolling(false, () => assert.fail("An idle course must not poll"))
  clock.tick(30_000)
  usePdfPolling(true, (signal) => {
    calls.push(signal)
    return new Promise((resolve) => { resolveRefresh = resolve })
  })
  clock.tick(2_000)
  assert.equal(calls.length, 1)
  clock.tick(60_000)
  assert.equal(calls.length, 1, "never overlap slow requests")
  for (const delay of [2_000, 3_000, 4_000, 8_000, 15_000, 30_000, 30_000]) {
    const before = calls.length
    resolveRefresh(true)
    await Promise.resolve()
    clock.tick(delay - 1)
    assert.equal(calls.length, before)
    clock.tick(1)
    assert.equal(calls.length, before + 1)
  }
  tab.hidden = true
  tab.dispatchEvent(new Event("visibilitychange"))
  resolveRefresh(true)
  await Promise.resolve()
  clock.tick(60_000)
  assert.equal(calls.length, 8)
  tab.hidden = false
  tab.dispatchEvent(new Event("visibilitychange"))
  assert.equal(calls.length, 9)
  resolveRefresh(false)
  await Promise.resolve()
  clock.tick(60_000)
  assert.equal(calls.length, 9, "stop after the server reports completion")
  cleanup()
  assert.equal(calls.at(-1).aborted, true)
})

test("documents are fetched through one owned-course query, including empty courses", async () => {
  let course = { documents: [] }
  let calls = 0
  const { GET } = load("app/api/documents/[courseId]/route.ts", {
    "next/server": { NextResponse: Response },
    "@/lib/supabase/server": { createClient: async () => ({
      auth: { getUser: async () => ({ data: { user: { id: "owner" } } }) },
      from(table) {
        calls++
        assert.equal(table, "courses")
        const filters = new Map()
        const query = {
          select: (columns) => { assert.equal(columns, "documents(*)"); return query },
          eq: (column, value) => { filters.set(column, value); return query },
          order: (column, options) => {
            assert.equal(column, "created_at")
            assert.deepEqual(options, { referencedTable: "documents", ascending: false })
            return query
          },
          maybeSingle: async () => {
            assert.deepEqual(Object.fromEntries(filters), { id: "course", user_id: "owner" })
            return { data: course, error: null }
          },
        }
        return query
      },
    }) },
  })
  const request = () => GET(new Request("https://socra.test/api/documents/course"),
    { params: Promise.resolve({ courseId: "course" }) })
  assert.deepEqual(await (await request()).json(), [])
  course = { documents: [{ id: "pdf", index_status: "ready" }] }
  assert.deepEqual(await (await request()).json(), course.documents)
  course = null
  assert.equal((await request()).status, 404)
  assert.equal(calls, 3)
})

test("Course Context returns PDF status and sections in the same response", async () => {
  const pending = { id: "pdf", filename: "course.pdf", index_stage: "Queued for indexing", summary_status: "pending" }
  const ready = { id: "ready", filename: "ready.pdf", content_hash: "current", index_status: "ready", summary_status: "ready" }
  const summary = { document_id: "ready", document_version: "current", level: "section", title: "Section",
    summary: "Current content", page_start: 1, page_end: 2 }
  let course = null
  const courseQuery = {
    select: () => courseQuery, eq: () => courseQuery, order: () => courseQuery,
    maybeSingle: async () => ({ data: course, error: null }),
  }
  const { isPdfProcessing } = load("lib/documents.ts", {})
  let summaryReads = 0
  const { GET } = load("app/api/documents/[courseId]/context/route.ts", {
    "next/server": { NextResponse: Response },
    "@/lib/documents": { isPdfProcessing },
    "@/lib/supabase/server": {
      createClient: async () => ({
        auth: { getUser: async () => ({ data: { user: { id: "owner" } } }) },
        from: (table) => { assert.equal(table, "courses"); return courseQuery },
      }),
      createServiceClient: async () => ({ from: (table) => {
        assert.equal(table, "document_summaries")
        const query = {
          select: () => query,
          eq: (column, value) => { assert.equal(column, "course_id"); assert.equal(value, "course"); return query },
          order: async () => {
            summaryReads++
            return { data: [summary, { ...summary, document_version: "stale" }], error: null }
          },
        }
        return query
      } }),
    },
  })
  const request = () => GET(new Request("https://socra.test/api/documents/course/context"),
    { params: Promise.resolve({ courseId: "course" }) })
  assert.equal((await request()).status, 404)
  assert.equal(summaryReads, 0)
  course = { documents: [pending, ready] }
  const [queued, indexed] = await (await request()).json()
  assert.equal(queued.processing, true)
  assert.equal(queued.filename, "course.pdf")
  assert.equal(indexed.processing, false)
  assert.deepEqual(indexed.sections, [{ title: "Section", summary: "Current content", pageStart: 1, pageEnd: 2 }])
})

test("upload reports a missing reservation function before contacting Storage", async (t) => {
  const uploadId = "00000000-0000-0000-0000-000000000001"
  const courseId = "00000000-0000-0000-0000-000000000002"
  const logs = t.mock.method(console, "error", () => {})
  let errorCode = "PGRST202"
  const { POST } = load("app/api/upload/route.ts", {
    "next/server": { NextResponse: Response },
    "@/lib/server/document-jobs": { uuidPattern: /^[0-9a-f-]{36}$/ },
    "@/lib/documents": { MAX_PDF_BYTES: 1024 },
    "@/lib/supabase/server": {
      createClient: async () => ({ auth: { getUser: async () => ({ data: { user: { id: "owner" } } }) } }),
      createServiceClient: async () => ({
        storage: { from: () => ({
          info: () => assert.fail("Reservation failed before Storage lookup"),
          createSignedUploadUrl: () => assert.fail("Reservation failed before signing"),
        }) },
        rpc: async (operation, args) => {
          assert.equal(operation, "reserve_pdf_upload")
          assert.equal(args.owner, "owner")
          assert.equal(args.upload_id, uploadId)
          return { data: null, error: { code: errorCode, message: "Internal details" } }
        },
      }),
    },
  })
  const reserve = () => POST(new Request("https://socra.test/api/upload", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "reserve", uploadId, courseId, filename: "course.pdf", size: 128, digest: "a".repeat(64) }),
  }))
  const missing = await reserve()
  assert.equal(missing.status, 503)
  assert.match((await missing.json()).error, /missing the upload functions/)
  assert.deepEqual(logs.mock.calls[0].arguments, [
    `pdf_upload_rpc_failed operation=reserve_pdf_upload request_id=${uploadId} code=PGRST202`,
  ])

  errorCode = "57014"
  const transient = await reserve()
  assert.equal(transient.status, 503)
  assert.equal((await transient.json()).error, "Could not prepare the upload. Retry shortly.")
})

test("PDF citations sign only an owned source and open its exact page", async () => {
  let signed = 0
  const id = "fixture"
  const auth = { id: "owner" }
  let document = null
  const route = load("app/api/documents/view/[id]/route.ts", {
    "@/lib/server/document-jobs": { ownedDocument: async (_, requested, owner) => {
      assert.equal(requested, id)
      assert.equal(owner, auth.id)
      return document
    } },
    "@/lib/supabase/server": {
      createClient: async () => ({ auth: { getUser: async () => ({ data: { user: auth } }) } }),
      createServiceClient: async () => ({ storage: { from: (bucket) => ({
        createSignedUrl: async (path, ttl) => {
          assert.equal(bucket, "documents")
          assert.equal(path, "owner/course/document.pdf")
          assert.equal(ttl, 120)
          signed++
          return { data: { signedUrl: "https://storage.example.test/signed?token=fixture" } }
        },
      }) } }),
    },
  })
  const get = (page) => route.GET(new Request(`https://example.test/api/documents/view/fixture?page=${page}`),
    { params: Promise.resolve({ id }) })
  assert.equal((await get(3)).status, 404)
  document = { course_id: "course", storage_path: "foreign/course/document.pdf", page_count: 5 }
  assert.equal((await get(3)).status, 404)
  document.storage_path = "owner/course/document.pdf"
  assert.equal((await get(6)).status, 404)
  assert.equal(signed, 0)
  const response = await get(3)
  assert.equal(response.status, 302)
  assert.equal(response.headers.get("location"), "https://storage.example.test/signed?token=fixture#page=3")
  assert.equal(response.headers.get("cache-control"), "private, no-store")
})

test("password recovery callback accepts only a verified recovery exchange", async () => {
  let redirectType = null
  let written
  const { GET } = load("app/auth/callback/route.ts", {
    "next/server": { NextResponse: { redirect: (url) => ({ url, cookies: { set: (...args) => { written = args } } }) } },
    "@/lib/supabase/server": { createClient: async () => ({ auth: {
      exchangeCodeForSession: async () => ({ data: { session: { access_token: "fixture" }, redirectType } }),
      getClaims: async () => ({ data: { claims: { session_id: "verified-session" } } }),
    } }) },
  })
  const call = (next) => GET(new Request(`https://socra.test/auth/callback?code=fixture&next=${next}`))
  assert.equal((await call("//external.example")).url.href, "https://socra.test/dashboard")
  assert.equal((await call("/reset-password")).url.pathname, "/forgot-password")
  assert.equal(written, undefined)
  redirectType = "recovery"
  assert.equal((await call("/reset-password")).url.pathname, "/reset-password")
  assert.equal(written[0], "socra_recovery")
  assert.equal(written[1], "verified-session")
  assert.equal(written[2].httpOnly, true)
})

test("explanation save requires an owned persisted assistant card", async () => {
  const course = "00000000-0000-0000-0000-000000000001"
  const session = "00000000-0000-0000-0000-000000000002"
  const message = "00000000-0000-0000-0000-000000000003"
  let owner = "other"
  let card
  const { readSavedExplanation } = load("lib/server/saved-explanation.ts", {
    "@/lib/server/document-jobs": { uuidPattern: /^[0-9a-f-]{36}$/ },
  })
  const client = { from(table) {
    const filters = new Map()
    const query = { select: () => query, eq: (key, value) => { filters.set(key, value); return query },
      maybeSingle: async () => ({ data: table === "sessions"
        ? (filters.get("courses.user_id") === owner && filters.get("course_id") === course ? { id: session } : null)
        : (filters.get("role") === "assistant" && filters.get("session_id") === session && filters.get("id") === message
          ? { metadata: { explanation: card } } : null) }),
    }
    return query
  } }
  const ref = { session_id: session, message_id: message, explanation: { definition: "Unverified input" } }
  assert.equal(await readSavedExplanation(client, "owner", course, ref), null)
  owner = "owner"
  assert.equal(await readSavedExplanation(client, "owner", course, ref), null)
  card = { definition: "Completed assistant explanation" }
  assert.equal(await readSavedExplanation(client, "owner", course, ref), card)
})

test("saved explanation converts to editable notes from the stored card", async () => {
  const card = { definition: "A star schema centers on a fact table.", intuition: "Think of a star.",
    sections: [{ heading: "Example", content: "Sales can be the fact table." }], citations: [] }
  let written
  const userClient = {
    auth: { getUser: async () => ({ data: { user: { id: "owner" } } }) },
    from(table) {
      const filters = new Map()
      const query = {
        select: () => query,
        eq: (key, value) => { filters.set(key, value); return query },
        single: async () => ({ data: table === "courses" && filters.get("user_id") === "owner" ? { id: "course" } : null }),
        maybeSingle: async () => ({ data: table === "library_items" && filters.get("user_id") === "owner" &&
          filters.get("item_type") === "explanation" && filters.get("id") === "item"
          ? { course_id: "course", content: { explanation: card, session_id: "session" } } : null }),
      }
      return query
    },
  }
  const { explanationNoteText } = load("lib/ai/explanation-note.ts", {})
  const { POST } = load("app/api/notebook/route.ts", {
    "next/server": { NextResponse: Response },
    "@/lib/ai/explanation-note": { explanationNoteText },
    "@/lib/server/notebook": { editableNote: ({ title, content, course_id }) => ({ title, content, course_id }) },
    "@/lib/server/saved-explanation": { readSavedExplanation: async () => null },
    "@/lib/supabase/server": {
      createClient: async () => userClient,
      createServiceClient: async () => ({ from: (table) => ({ insert: (data) => {
        assert.equal(table, "notebook_notes")
        written = data
        return { select: () => ({ single: async () => ({ data: { id: "note", ...data } }) }) }
      } }) }),
    },
  })
  const request = (id) => new Request("https://socra.test/api/notebook", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "Star schema", course_id: "course", library_item_id: id,
      source_type: "explanation", content: "Unverified content" }),
  })
  assert.equal((await POST(request("foreign-item"))).status, 404)
  assert.equal(written, undefined)
  const response = await POST(request("item"))
  assert.equal(response.status, 201)
  assert.equal((await response.json()).id, "note")
  assert.match(written.content, /Sales can be the fact table[.]/)
  assert.doesNotMatch(written.content, /Unverified content/)
  assert.equal(written.source_data.session_id, "session")
})
