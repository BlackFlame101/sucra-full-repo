// Runs the production hook in Chromium with a fake WebSocket and Supabase session.
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { pathToFileURL } from "node:url"
import ts from "typescript"

const browser = process.env.SOCRA_TEST_BROWSER
if (!browser) throw new Error("Set SOCRA_TEST_BROWSER to a Chromium or Chrome executable.")
const require = createRequire(import.meta.url)
const root = new URL("../", import.meta.url)
const sources = {
  react: readFileSync(require.resolve("react").replace("index.js", "cjs/react.production.js"), "utf8"),
  "react-dom": readFileSync(require.resolve("react-dom").replace("index.js", "cjs/react-dom.production.js"), "utf8"),
  "react-dom/client": readFileSync(require.resolve("react-dom/client").replace("client.js", "cjs/react-dom-client.production.js"), "utf8"),
  scheduler: readFileSync(require.resolve("scheduler").replace("index.js", "cjs/scheduler.production.js"), "utf8"),
  "@/lib/supabase/client": 'exports.createClient = () => ({auth:{getSession:async()=>({data:{session:{access_token:"fixture"}}})}})',
}
for (const [name, path] of [
  ["@/lib/socra-ws", "lib/socra-ws.ts"],
  ["@/lib/explanation-v2", "lib/explanation-v2.ts"],
  ["@/lib/educational-document", "lib/educational-document.ts"],
  ["@/lib/documents/pdf-page", "lib/documents/pdf-page.ts"],
  ["@/lib/ai/model-policy", "lib/ai/model-policy.ts"],
  ["model-resolver", "lib/ai/model-resolver.ts"],
  ["settings", "hooks/useUserSettings.ts"],
  ["hook", "hooks/useSocraChat.ts"],
]) {
  sources[name] = ts.transpileModule(readFileSync(new URL(path, root), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
}
const suite = async function (modules) {
  const cache = {}
  const load = (name) => {
    if (name === "./explanation-v2") name = "@/lib/explanation-v2"
    if (name === "./educational-document") name = "@/lib/educational-document"
    if (!cache[name]) {
      const entry = { exports: {} }
      new Function("module", "exports", "require", "process", modules[name])(
        entry, entry.exports, load, { env: { NODE_ENV: "production" } },
      )
      cache[name] = entry.exports
    }
    return cache[name]
  }
  const React = load("react")
  const { createRoot } = load("react-dom/client")
  const { useSocraChat } = load("hook")
  const { useUserSettings } = load("settings")
  const { PROVIDERS } = load("model-resolver")
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  const googleModels = PROVIDERS.find(({ id }) => id === "google").models
  check(googleModels.every(({ id }) => !id.startsWith("gemini-2.5-flash")), "Blocked model appeared in Settings")
  const tick = (ms = 10) => new Promise((resolve) => setTimeout(resolve, ms))
  const wait = async (condition, message) => {
    for (let i = 0; i < 50; i++) {
      if (condition()) return
      await tick()
    }
    throw new Error(message)
  }
  // Chromium virtual time advances timers without issuing compositor frames.
  window.requestAnimationFrame = (callback) => setTimeout(callback, 16)
  window.cancelAnimationFrame = clearTimeout
  const browserTimer = window.setTimeout.bind(window)
  window.setTimeout = (callback, delay, ...args) => browserTimer(callback, delay === 200_000 ? 300 : delay, ...args)
  const sockets = []
  class FakeSocket extends EventTarget {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSED = 3
    readyState = FakeSocket.CONNECTING
    sent = []
    constructor() { super(); sockets.push(this) }
    open() {
      this.readyState = FakeSocket.OPEN
      this.dispatchEvent(new Event("open"))
    }
    send(raw) { this.sent.push(JSON.parse(raw)) }
    close(code = 1006) {
      this.readyState = FakeSocket.CLOSED
      this.dispatchEvent(new CloseEvent("close", { code }))
    }
    push(type, content, request_id, sequence) {
      this.dispatchEvent(new MessageEvent("message", {
        data: JSON.stringify({ type, content, request_id, session_id: "fixture", sequence, version: 2 }),
      }))
    }
  }
  Object.defineProperty(window, "WebSocket", { value: FakeSocket })
  localStorage.setItem("socra_api_keys", JSON.stringify({ google: "fixture-google-key" }))
  localStorage.setItem("socra_model_pref", JSON.stringify({ provider: "google", model: " MODELS/GEMINI-2.5-FLASH-LITE " }))
  let settings
  let chat
  let context
  function Harness() {
    const currentSettings = useUserSettings()
    React.useLayoutEffect(() => { settings = currentSettings }, [currentSettings])
    const view = useSocraChat({ sessionId: "fixture", courseId: "course", language: "en", recoverInterrupted: true,
      onContext: (value) => { context = value } })
    React.useLayoutEffect(() => { chat = view }, [view])
    return React.createElement("div", null, view.status + " " + view.messages.length)
  }
  const host = document.getElementById("fixture")
  const app = createRoot(host)
  app.render(React.createElement(Harness))
  await wait(() => sockets.length === 1, "Expected one preconnected socket")
  await wait(() => settings?.loaded, "Model preferences did not load")
  check(settings.getActiveConfig().model === "gemini-3.5-flash-lite", "Saved Flash preference was not migrated")
  check(settings.getActiveConfig().apiKey === "fixture-google-key", "Saved Gemini key was lost")
  check(JSON.parse(localStorage.getItem("socra_model_pref")).model === "gemini-3.5-flash-lite", "Migration was not persisted")
  settings.setModelPref({ provider: "google", model: "gemini-3.8-flash" })
  await wait(() => settings.getActiveConfig().model === "gemini-3.8-flash", "An allowed model selection was ignored")
  settings.setModelPref({ provider: "google", model: "gemini-flash-latest" })
  await wait(() => settings.getActiveConfig().model === "gemini-3.5-flash-lite", "A floating Flash alias was accepted")
  chat.sendMessage({ text: "Test prompt", mode: "explain" })
  await wait(() => chat.messages.length === 2, "Immediate user message and placeholder missing")
  check(chat.status === "submitted" && sockets[0].sent.length === 0, "UI waited for the network")

  const authenticate = async (socket) => {
    socket.open()
    await wait(() => socket.sent[0]?.action === "authenticate", "Missing auth handshake")
    check(socket.sent[0].version === 2, "Missing protocol version")
    socket.push("connected")
    await wait(() => socket.sent.length === 2, "Missing action after auth")
  }
  const socket = sockets[0]
  await authenticate(socket)
  const id = socket.sent[1].requestId
  socket.push("request_accepted", null, id, 1)
  socket.push("progress", { stage: "Checking course pages." }, id, 2)
  await wait(() => chat.progress === "Checking course pages.", "Slow request stage missing")
  socket.push("content_delta", { text: "First " }, id, 3)
  socket.push("content_delta", { text: "draft" }, id, 4)
  socket.push("content_delta", { text: "duplicate" }, id, 4)
  await wait(() => chat.messages[1].parts[0].text === "First draft", "Delta batching or sequence filtering failed")
  const unit = { logical_id: "u", title: "Unit", content_version: "hash", coverage: "partial",
    verification: "unreviewed", blocks: [{ block_id: "b", kind: "explanation", text: "Draft block",
      provenance: "supplementary", source_indexes: [] }], sources: [], missing_item_ids: ["requirement"],
    unverifiable_source: [], verified_facts: [] }
  const draft = { request_id: id, document_id: "pdf", generation: 4, source_hash: "pdf-hash",
    stage: "draft", output: unit, change_log: [] }
  const ready = { ...draft, stage: "ready", output: { ...unit, coverage: "not_generated", blocks: [] } }
  const state = () => [...chat.explanationUnits.values()][0]
  socket.push("unit_draft", { ...draft, output: { ...unit, logical_id: "foreign" } }, "another-request", 1)
  socket.push("prep_status", { document_id: "pdf", status: "loading" }, id, 5)
  await wait(() => chat.explanationTurns.get(id)?.stream.preparation?.status === "loading", "Preparation was lost before the first draft")
  socket.push("unit_checking", unit, id, 7)
  socket.push("unit_draft", draft, id, 6)
  await wait(() => state()?.lifecycle === "checking", "Late draft did not retain the checking lifecycle")
  check(chat.explanationUnits.size === 1 && state().current.output.blocks[0].text === "Draft block",
    "Draft content was lost or a foreign request entered the current turn")
  socket.push("unit_ready", ready, id, 8)
  socket.push("unit_draft", draft, id, 6)
  await wait(() => state()?.lifecycle === "ready", "Ready unit was missing")
  check(state().current.output.coverage === "not_generated" && state().versions.length === 2,
    "Readiness promoted coverage or duplicate drafts produced duplicate versions")
  chat.stop()
  check(socket.sent.at(-1).action === "cancel", "Stop did not reach the server")
  socket.push("cancelled", null, id, 9)
  await wait(() => chat.status === "ready" && chat.messages[1].metadata?.partial, "Cancellation stayed busy")
  chat.regenerate()
  await wait(() => socket.sent.length === 4, "Retry was never dispatched")
  check(socket.sent.at(-1).requestId === id && chat.messages.length === 2, "Retry duplicated the prompt")
  socket.push("error", { code: "FAILED", message: "Temporary rejection" }, id, 1)
  await wait(() => chat.status === "error", "Rejection stayed busy")
  chat.regenerate()
  await wait(() => socket.sent.length === 5, "Retry after rejection failed")
  socket.close()
  await wait(() => chat.status === "error", "Disconnect stayed busy")
  chat.regenerate()
  await wait(() => sockets.length === 2, "Retry did not reconnect")
  const recovered = sockets[1]
  await authenticate(recovered)
  check(recovered.sent[1].requestId === id && chat.messages.length === 2, "Reconnect lost the idempotency key")
  recovered.push("unit_ready", { ...ready, replayed: true }, id, 1)
  await wait(() => state()?.lifecycle === "ready", "Cancellation lost a ready checkpoint")
  check(state().versions.length === 2, "Reconnect duplicated the unit version")
  const explanation = { definition: "Verified", check_question: "Why compare the same metric?" }
  recovered.push("content_delta", { text: explanation.check_question }, id, 1)
  await wait(() => chat.messages[1].parts[0].text === explanation.check_question, "Question preview was missing")
  recovered.push("card_ready", { kind: "explanation", card: explanation }, id, 2)
  await wait(() => chat.messages[1].metadata?.explanation, "Final card did not replace the preview")
  // History can already contain the row that recovery is about to acknowledge.
  chat.setMessages((history) => [...history, {
    ...history[1], id: "persisted", metadata: { ...history[1].metadata, persisted: true, request_id: id },
  }])
  await wait(() => chat.messages.length === 3, "Restored row was not loaded into the fixture")
  recovered.push("response_complete", { message_id: "persisted", text: "Course explanation ready." }, id, 3)
  await wait(() => chat.status === "ready" && chat.messages[1].id === "persisted", "Completion did not release input")
  check(chat.messages.filter((message) => message.id === "persisted").length === 1, "Replay duplicated a persisted explanation card")
  check(chat.messages[1].metadata.explanation.definition === "Verified", "Final card was lost")
  check(state()?.current.output.coverage === "not_generated", "Legacy card overwrote structured event state")
  recovered.push("context_update", { key_terms: ["late"] }, id, 4)
  await wait(() => context?.key_terms[0] === "late", "Late context was lost")
  recovered.push("done", null, id, 5)
  chat.regenerate()
  await wait(() => recovered.sent.length === 3, "Regenerate did not dispatch")
  check(recovered.sent.at(-1).requestId !== id && chat.messages.length === 4, "Regenerate should create a new turn")
  const lateUnit = { ...draft, stage: "ready", output: { ...unit, logical_id: "earlier-unit" } }
  recovered.push("unit_ready", lateUnit, id, 6)
  recovered.push("unit_correction", { logical_id: "earlier-unit", content_version: "hash",
    version_request_id: id, generation: 4, block_id: "b", old_quote: "Old text", new_quote: "Draft block" }, id, 7)
  await wait(() => chat.explanationTurns.get(id)?.stream.corrections.length === 1, "Late correction was lost")
  check(!chat.explanationTurns.has(recovered.sent.at(-1).requestId), "An earlier correction entered the active turn")
  app.unmount()

  const reloaded = createRoot(host)
  reloaded.render(React.createElement(Harness))
  await wait(() => chat.canRegenerate, "Refresh did not expose recovery")
  check(chat.progress === "Recover the last request.", "Refresh recovery stage is missing")
  chat.regenerate()
  await wait(() => sockets.length === 3, "Refresh retry did not connect")
  const afterRefresh = sockets[2]
  await authenticate(afterRefresh)
  check(afterRefresh.sent[1].requestId === recovered.sent.at(-1).requestId, "Refresh retry created a duplicate request")
  await wait(() => chat.error?.message.includes("stopped responding"), "Silent socket did not time out")
  check(chat.status === "error", "Timeout left chat busy")
  const next = { action: "continue_learning", request_id: "fixture-next", logical_id: "next-unit" }
  chat.runUnitAction("stored-turn", next, "Continuer : II.4")
  await wait(() => sockets.length === 4, "Continue did not reconnect")
  const actionsSocket = sockets[3]
  await authenticate(actionsSocket)
  let sent = actionsSocket.sent.at(-1)
  check(sent.action === "continue_learning" && sent.mode === "explain" && sent.fromRequestId === "stored-turn"
    && sent.requestId === next.request_id && !sent.unitId, "Continue altered the backend descriptor")
  actionsSocket.push("response_complete", { message_id: "continued", text: "Next unit saved." }, next.request_id, 1)
  await wait(() => chat.status === "ready", "Continue did not finish")
  const deepen = { action: "deepen_unit", request_id: "fixture-deepen", logical_id: "earlier-partial" }
  chat.runUnitAction("stored-turn", deepen, "Approfondir II.3")
  await wait(() => actionsSocket.sent.length === 3, "Deepen did not send")
  sent = actionsSocket.sent.at(-1)
  check(sent.action === "deepen_unit" && sent.mode === "explain" && sent.fromRequestId === "stored-turn"
    && sent.requestId === deepen.request_id && sent.unitId === deepen.logical_id, "Deepen lost its exact unit or request ID")
  reloaded.unmount()
}

const temp = mkdtempSync(join(tmpdir(), "socra-browser-"))
try {
  const fixture = join(temp, "chat.html")
  const moduleData = JSON.stringify(sources).replaceAll("</script", "<\\/script")
  writeFileSync(fixture, "<main id=fixture></main><output id=result>pending</output><script>(" +
    suite.toString() + ")(" + moduleData +
    ").then(()=>result.textContent='PASS').catch(error=>result.textContent=error.stack)</script>")
  const result = spawnSync(browser, ["--no-sandbox", "--disable-gpu", "--no-proxy-server", "--headless",
    "--virtual-time-budget=10000", "--dump-dom", pathToFileURL(fixture).href], { cwd: temp, encoding: "utf8", timeout: 30_000, maxBuffer: 8_000_000 })
  const outcome = result.stdout?.match(/<output id="result">([^<]*)<\/output>/)?.[1]
  assert.equal(outcome, "PASS", result.error?.message || outcome || result.stderr)
  console.log("Chat browser smoke passed")
} finally {
  rmSync(temp, { recursive: true, force: true })
}
