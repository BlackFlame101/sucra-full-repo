import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import ts from "typescript"

const exports = {}
const CHUNK = 6 * 1024 * 1024
const source = readFileSync(new URL("../lib/pdf/direct-upload.ts", import.meta.url), "utf8")
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
new Function("exports", "require", compiled)(exports, () => ({ TUS_CHUNK_BYTES: CHUNK }))
const { uploadPdf, uploadInParallel } = exports
const endpoint = "https://storage.example.test/storage/v1/upload/resumable/sign"
const url = endpoint + "/upload-resource"
const small = new File(["%PDF-1.7 contents"], "small.pdf")
const large = new File(["%PDF-1.7", new Uint8Array(CHUNK + 1024)], "large.pdf")

function fixture(t, { interrupted = false, quota = false, badLocation = false } = {}) {
  const actions = []
  const requests = []
  const fileState = { offset: 0 }
  globalThis.fetch = async (target, options) => {
    assert.equal(target, "/api/upload")
    assert.equal(typeof options.body, "string")
    const payload = JSON.parse(options.body)
    actions.push(payload)
    if (payload.action === "reserve") {
      const target = payload.size > CHUNK ? { path: "fixture.pdf", token: "test", resumableUrl: endpoint }
        : { signedUrl: "https://storage.example.test/signed" }
      return Response.json(target)
    }
    if (quota) {
      quota = false
      return Response.json({ error: "Queue is full." }, { status: 429 })
    }
    return Response.json({ document: { id: "fixture" } })
  }
  globalThis.XMLHttpRequest = class extends EventTarget {
    headers = {}
    response = {}
    upload = new EventTarget()
    open(method, location) { this.method = method; this.location = location }
    setRequestHeader(key, value) { this.headers[key] = value }
    getResponseHeader(key) { return this.response[key] ?? null }
    abort() { this.onabort(); this.onloadend() }
    send(body) {
      requests.push({ method: this.method, size: body?.size, headers: this.headers, location: this.location })
      queueMicrotask(() => {
        this.status = 200
        if (this.method === "POST") this.response.Location = badLocation ? "https://wrong.example.test/anything" : url
        if (this.method === "HEAD") this.response["Upload-Offset"] = String(fileState.offset)
        if (this.method === "PATCH") {
          fileState.offset += body.size
          this.response["Upload-Offset"] = String(fileState.offset)
          if (interrupted) {
            interrupted = false
            this.onerror()
            this.onloadend()
            return
          }
        }
        if (body?.size) this.upload.dispatchEvent(Object.assign(new Event("progress"), { loaded: body.size }))
        this.onload()
        this.onloadend()
      })
    }
  }
  t.after(() => { delete globalThis.XMLHttpRequest })
  return { actions, requests }
}

test("small PDF transfers directly and queue retries do not retransmit bytes", async (t) => {
  const { actions, requests } = fixture(t, { quota: true })
  const state = {}
  const stages = []
  const upload = () => uploadPdf(small, "course", "id", state, new AbortController().signal,
    (stage, bytes) => stages.push([stage, bytes]))
  await assert.rejects(upload(), { status: 429 })
  assert.equal((await upload()).document.id, "fixture")
  assert.deepEqual(actions.map((item) => item.action), ["reserve", "finish", "finish"])
  assert.match(actions[0].digest, /^[0-9a-f]{64}$/)
  assert.deepEqual(requests.map((item) => [item.method, item.size]), [["PUT", small.size]])
  assert.ok(stages.some(([stage, bytes]) => stage === "uploading" && bytes === small.size))
})

test("large PDF resumes from Storage's confirmed offset", async (t) => {
  const { actions, requests } = fixture(t, { interrupted: true })
  const state = {}
  const upload = () => uploadPdf(large, "course", "id", state, new AbortController().signal, () => {})
  await assert.rejects(upload(), /interrupted/)
  assert.equal(actions.some((item) => item.action === "finish"), false)
  await upload()
  assert.deepEqual(requests.map((item) => item.method), ["POST", "PATCH", "HEAD", "PATCH"])
  assert.equal(requests.at(-1).headers["Upload-Offset"], String(CHUNK))
  assert.equal(requests.at(-1).size, large.size - CHUNK)
})

test("rejects a Storage redirect to an unexpected origin", async (t) => {
  const { requests } = fixture(t, { badLocation: true })
  await assert.rejects(uploadPdf(large, "course", "id", {}, new AbortController().signal, () => {}), /unexpected upload destination/)
  assert.deepEqual(requests.map((item) => item.method), ["POST"])
})

test("batch concurrency stays at two", async () => {
  let active = 0
  let peak = 0
  const done = []
  await uploadInParallel([1, 2, 3, 4, 5], async (item) => {
    peak = Math.max(peak, ++active)
    await new Promise((resolve) => setTimeout(resolve, 4))
    done.push(item)
    active--
  })
  assert.equal(peak, 2)
  assert.deepEqual(done.sort(), [1, 2, 3, 4, 5])
})
