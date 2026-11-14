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
        data: JSON.stringify({ type, content, request_id, sequence, version: 2 }),
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
  chat.stop()
  check(socket.sent.at(-1).action === "cancel", "Stop did not reach the server")
  socket.push("cancelled", null, id, 5)
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
  recovered.push("card_ready", { kind: "explanation", card: { definition: "Verified" } }, id, 1)
  recovered.push("response_complete", { message_id: "persisted", text: "Course explanation ready." }, id, 2)
  await wait(() => chat.status === "ready" && chat.messages[1].id === "persisted", "Completion did not release input")
  check(chat.messages[1].metadata.explanation.definition === "Verified", "Final card was lost")
  recovered.push("context_update", { key_terms: ["late"] }, id, 3)
  await wait(() => context?.key_terms[0] === "late", "Late context was lost")
  recovered.push("done", null, id, 4)
  chat.regenerate()
  await wait(() => recovered.sent.length === 3, "Regenerate did not dispatch")
  check(recovered.sent.at(-1).requestId !== id && chat.messages.length === 4, "Regenerate should create a new turn")
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
