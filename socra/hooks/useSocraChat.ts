"use client"

/**
 * Drop-in replacement for `useChat` from `@ai-sdk/react` that streams from
 * the Python LangGraph backend over WebSocket instead of HTTP SSE.
 *
 * Same return shape (`messages: UIMessage[]`, `status`, `setMessages`, ...)
 * so the existing `ChatPanel` / `MessageList` / `Message` components work
 * with no changes whatsoever.
 *
 * Adds two new callbacks because the WebSocket also pushes the diagnostic
 * report (first turn) and the evaluation result (after substantive answers):
 *   - `onDiagnostic(d)` — fired exactly once per fresh session
 *   - `onContext(e)`    — fired when the Évaluateur ran for the turn
 */
import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react"
import type { UIMessage } from "ai"
import { createClient } from "@/lib/supabase/client"
import { applyExplanationEvent, inquiryExplanationUnits, restoreExplanationTurns, type ExplanationStream, type UnitAction } from "@/lib/explanation-v2"
import {
  buildChatWsUrl,
  parseServerMessage,
  type DiagnosticReport,
  type EvaluationResult,
  type LearningMode,
  type NotebookContext,
  type PublicCard,
  type PublicCorrection,
  type PublicExercise,
  type ExplanationPayload,
  type PublicSolution,
} from "@/lib/socra-ws"

// Mirrors the @ai-sdk/react `useChat` status union so existing UI (ChatInput,
// ChatPanel, MessageList) works unchanged — including the "ready" idle state.
export type ChatStatus = "ready" | "connecting" | "submitted" | "streaming" | "error"

interface UseSocraChatOpts {
  sessionId: string
  recoverInterrupted?: boolean
  courseId: string
  /** Optional per-request LLM config from the Settings dialog. Google and Groq
   *  are forwarded to the backend; other providers are not yet supported there. */
  llmConfig?: { apiKey?: string; provider?: string; model?: string }
  language: "fr" | "en"
  onDiagnostic?: (d: DiagnosticReport) => void
  onContext?: (e: EvaluationResult) => void
  onExercise?: (e: PublicExercise) => void
  onExplanation?: (e: ExplanationPayload) => void
  onCorrection?: (e: PublicCorrection) => void
  onSolution?: (e: PublicSolution) => void
  onError?: (err: Error) => void
}

interface UseSocraChatReturn {
  messages: UIMessage[]
  explanationTurns: ReturnType<typeof restoreExplanationTurns>
  explanationUnits: ReturnType<typeof inquiryExplanationUnits>
  status: ChatStatus
  progress: string
  connection: string
  stop: () => void
  error: Error | null
  sendMessage: (m: ChatMessageRequest) => void
  runUnitAction: (from: string, command: UnitAction, label: string) => void
  submitAttempt: (attempt: { exerciseId: string; answer: string; hintsUsed: number }) => void
  revealSolution: (exerciseId: string) => void
  restoreExercise: () => void
  setMessages: Dispatch<SetStateAction<UIMessage[]>>
  regenerate: () => void
  canRegenerate: boolean
  interrupted: { text: string; mode: LearningMode } | null
  /** Force-close the underlying socket. Mostly useful for tests. */
  disconnect: () => void
}

type ChatMessageRequest = { text: string; displayText?: string; mode?: LearningMode; notebook?: NotebookContext
  continuation?: { from: string; requestId: string } }

type Turn = {
  id: string
  body: Record<string, unknown>
  display?: string
  sequence: number
  sent: boolean
}

function localMessage(id: string, role: "user" | "assistant", text: string): UIMessage {
  return { id, role, parts: [{ type: "text", text }] }
}

export function useSocraChat(opts: UseSocraChatOpts): UseSocraChatReturn {
  const { sessionId, courseId, recoverInterrupted } = opts
  const recoveryKey = "socra:turn:" + sessionId
  const [messages, setMessages] = useState<UIMessage[]>([])
  const explanationTurns = useMemo(() => restoreExplanationTurns(messages), [messages])
  const explanationUnits = useMemo(() => inquiryExplanationUnits(explanationTurns), [explanationTurns])
  const [status, setStatus] = useState<ChatStatus>("ready")
  const [progress, setProgress] = useState("")
  const [connection, setConnection] = useState("Disconnected")
  const [interrupted, setInterrupted] = useState<{ text: string; mode: LearningMode } | null>(null)
  const [canRegenerate, setCanRegenerate] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const active = useRef<Turn | null>(null)
  const last = useRef<Turn | null>(null)
  const retryable = useRef(false)
  const socket = useRef<WebSocket | null>(null)
  const ready = useRef<Promise<WebSocket> | null>(null)
  const timeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const frame = useRef(0)
  const buffer = useRef("")
  const reconnect = useRef<(() => void) | null>(null)
  const callbacks = useRef(opts)
  useEffect(() => { callbacks.current = opts }, [opts])

  const updateDraft = useCallback((turn: Turn, update: (message: UIMessage) => UIMessage) => {
    setMessages((previous) => previous.map((message) => message.id === turn.id ? update(message) : message))
  }, [])

  const flush = useCallback(() => {
    if (frame.current) cancelAnimationFrame(frame.current)
    frame.current = 0
    const text = buffer.current
    buffer.current = ""
    const turn = active.current
    if (turn && text) updateDraft(turn, (message) => {
      const part = message.parts[0]
      return { ...message, parts: [{ type: "text", text: (part?.type === "text" ? part.text : "") + text }] }
    })
  }, [updateDraft])

  const finish = useCallback((partial: boolean, stage = "", failed = false) => {
    flush()
    clearTimeout(timeout.current)
    const turn = active.current
    if (partial && turn) updateDraft(turn, (message) => {
      const metadata = message.metadata as { explanationStream?: ExplanationStream } | undefined
      return { ...message, metadata: { ...metadata, partial: true,
        ...(metadata?.explanationStream ? { explanationStream: { ...metadata.explanationStream, interrupted: true, failed } } : {}),
      } }
    })
    active.current = null
    retryable.current = partial
    if (!partial && turn) {
      try { sessionStorage.removeItem(recoveryKey) } catch { /* Storage is optional. */ }
    }
    setCanRegenerate(Boolean(turn && (partial || !turn.body.action)))
    setProgress(stage)
    setStatus("ready")
  }, [flush, recoveryKey, updateDraft])

  const fail = useCallback((cause: unknown) => {
    const failure = cause instanceof Error ? cause : new Error("Could not reach the tutor. Try again.")
    finish(true, "", true)
    setStatus("error")
    setError(failure)
    callbacks.current.onError?.(failure)
  }, [finish])

  const waitForTurn = useCallback(() => {
    clearTimeout(timeout.current)
    timeout.current = setTimeout(() => {
      fail(new Error("The tutor stopped responding. Try again."))
      socket.current?.close()
    }, 200_000)
  }, [fail])

  const ensureSocket = useCallback((): Promise<WebSocket> => {
    if (ready.current && socket.current &&
        (socket.current.readyState === WebSocket.CONNECTING || socket.current.readyState === WebSocket.OPEN)) {
      return ready.current
    }
    setConnection("Connecting")
    let ws: WebSocket
    try {
      ws = new WebSocket(buildChatWsUrl(sessionId))
    } catch (cause) {
      setConnection("Disconnected")
      return Promise.reject(cause)
    }
    socket.current = ws
    ready.current = new Promise<WebSocket>((resolve, reject) => {
      let denied = false
      const handshake = setTimeout(() => {
        reject(new Error("The tutor could not connect in time. Try again."))
        ws.close()
      }, 85_000)
      ws.addEventListener("open", () => {
        void (async () => {
          const { data } = await createClient().auth.getSession()
          if (!data.session?.access_token) {
            denied = true
            throw new Error("Sign in again to open this inquiry.")
          }
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: "authenticate", version: 2, courseId, accessToken: data.session.access_token }))
          }
        })().catch((cause: unknown) => { reject(cause); ws.close() })
      }, { once: true })
      ws.addEventListener("error", () => reject(new Error("Could not connect to the tutor.")), { once: true })
      ws.addEventListener("close", (event) => {
        clearTimeout(handshake)
        reject(new Error("The tutor disconnected. Try again."))
        if (socket.current !== ws) return
        socket.current = null
        ready.current = null
        setConnection("Disconnected")
        if (active.current) fail(new Error("The tutor disconnected. Retry to recover the response."))
        if (!denied && event.code !== 1000 && event.code !== 1008) reconnect.current?.()
      })
      ws.addEventListener("message", (event) => {
        if (socket.current !== ws) return
        const msg = parseServerMessage(typeof event.data === "string" ? event.data : "")
        if (!msg || (msg.session_id && msg.session_id !== sessionId)) return
        if (msg.type === "connected") {
          clearTimeout(handshake)
          setConnection("Connected")
          resolve(ws)
          return
        }
        if (msg.type === "error" && typeof msg.content !== "string" && msg.content.code === "AUTH_REQUIRED") {
          denied = true
          const authError = Object.assign(new Error(msg.content.message), { code: msg.content.code })
          reject(authError)
          if (active.current) fail(authError)
          ws.close()
          return
        }
        if (msg.type === "context_update" || msg.type === "context") {
          callbacks.current.onContext?.(msg.content)
          return
        }
        const turn = active.current
        switch (msg.type) {
          case "prep_status":
          case "unit_draft":
          case "unit_checking":
          case "unit_ready":
          case "unit_correction": {
            const activeDraft = turn && turn.id === msg.request_id ? turn.id : undefined
            if (activeDraft) waitForTurn()
            setMessages((previous) => {
              const index = previous.findLastIndex((message) => {
                const metadata = message.metadata as { request_id?: string } | undefined
                return message.role === "assistant" &&
                  (activeDraft ? message.id === activeDraft : metadata?.request_id === msg.request_id)
              })
              const message = previous[index]
              if (!message) return previous
              const metadata = message.metadata as { explanationStream?: ExplanationStream } | undefined
              const stream = applyExplanationEvent(metadata?.explanationStream, msg, msg.sequence)
              return stream === metadata?.explanationStream ? previous
                : previous.with(index, { ...message, metadata: { ...metadata, explanationStream: stream } })
            })
            return
          }
        }
        if (!turn || (msg.request_id && msg.request_id !== turn.id)) return
        if (msg.sequence !== undefined) {
          if (msg.sequence <= turn.sequence) return
          turn.sequence = msg.sequence
        }
        waitForTurn()
        const attach = (key: string, value: unknown) => {
          updateDraft(turn, (message) => ({
            ...message, metadata: { ...(message.metadata as object), [key]: value },
          }))
        }
        const onCard = (card: PublicCard) => {
          attach(card.kind, card.card)
          switch (card.kind) {
            case "exercise": callbacks.current.onExercise?.(card.card); break
            case "explanation": callbacks.current.onExplanation?.(card.card); break
            case "correction": callbacks.current.onCorrection?.(card.card); break
            case "solution": callbacks.current.onSolution?.(card.card); break
          }
        }
        switch (msg.type) {
          case "document_snapshot":
            attach("explanation", msg.content)
            setStatus("streaming")
            break
          case "request_accepted":
            setProgress("Waiting for the tutor.")
            break
          case "diagnostic":
            callbacks.current.onDiagnostic?.(msg.content)
            break
          case "content_delta":
          case "token": {
            const text = msg.type === "token" ? msg.content : msg.content.text
            if (text === null) {
              flush()
              updateDraft(turn, (message) => ({ ...message, parts: [{ type: "text", text: "" }] }))
            } else if (text) {
              buffer.current += text
              if (!frame.current) frame.current = requestAnimationFrame(flush)
              setStatus("streaming")
            }
            break
          }
          case "card_ready": onCard(msg.content); break
          case "exercise": onCard({ kind: "exercise", card: msg.content }); break
          case "explanation": onCard({ kind: "explanation", card: msg.content }); break
          case "correction": onCard({ kind: "correction", card: msg.content }); break
          case "solution": onCard({ kind: "solution", card: msg.content }); break
          case "response_complete": {
            flush()
            const { message_id: savedId, text } = msg.content
            setMessages((previous) => {
              const draft = previous.find((message) => message.id === turn.id)
              if (!draft) return previous
              const saved = savedId && previous.find((message) => message.id === savedId)
              const completed: UIMessage = {
                ...draft,
                id: savedId || draft.id,
                metadata: {
                  ...(saved ? saved.metadata as object : {}),
                  ...(draft.metadata as object),
                  request_id: turn.id,
                  persisted: Boolean(savedId),
                },
                parts: [{ type: "text", text }],
              }
              // Recovery and history can both observe the same persisted response.
              return previous.flatMap((message) => message.id === draft.id ? [completed]
                : message.id === savedId ? [] : [message])
            })
            finish(false)
            break
          }
          case "cancelled": finish(true, "Generation stopped."); break
          case "done": finish(false); break
          case "progress": setProgress(msg.content.stage); break
          case "error":
            fail(typeof msg.content === "string" ? new Error(msg.content)
              : Object.assign(new Error(msg.content.message), { code: msg.content.code }))
            break
        }
      })
    })
    return ready.current
  }, [courseId, fail, finish, flush, sessionId, updateDraft, waitForTurn])

  const start = useCallback((turn: Turn, reuse: boolean) => {
    if (active.current) return
    active.current = turn
    last.current = turn
    retryable.current = false
    setCanRegenerate(false)
    setInterrupted(null)
    setStatus("submitted")
    setProgress(connection === "Connected" ? "Waiting for the tutor." : "Connecting to the tutor.")
    setError(null)
    if (turn.display) {
      try { sessionStorage.setItem(recoveryKey, JSON.stringify({ id: turn.id, body: turn.body, display: turn.display })) }
      catch { /* The active turn can still be retried in memory. */ }
      const display = turn.display
      setMessages((previous) => {
        const priorDraft = reuse ? previous.find((message) => message.id === turn.id) : undefined
        const priorStream = (priorDraft?.metadata as { explanationStream?: ExplanationStream } | undefined)?.explanationStream
        const savedPrompt = reuse && previous.some((message) => message.role === "user" && message.id !== turn.id + ":user"
          && (message.metadata as { request_id?: string } | undefined)?.request_id === turn.id)
        const history = reuse ? previous.filter((message) =>
          message.id !== turn.id && message.id !== turn.id + ":user"
        ) : previous
        const notebookAction = (turn.body.notebook as NotebookContext | undefined)?.action
        const metadata = { request_id: turn.id, ...(notebookAction ? { notebook_action: notebookAction } : {}),
          ...(typeof turn.body.fromRequestId === "string" ? { unitActionFrom: turn.body.fromRequestId } : {}) }
        return [...history, ...(savedPrompt ? [] : [{ ...localMessage(turn.id + ":user", "user", display), metadata }]),
          { ...localMessage(turn.id, "assistant", ""), metadata: turn.body.mode === "explain"
            ? { ...metadata, explanationPreview: true, ...(priorStream ? { explanationStream: {
              ...priorStream, interrupted: false, failed: false, preparationSequence: undefined,
            } } : {}) } : metadata }]
      })
    }
    waitForTurn()
    void ensureSocket().then(async (ws) => {
      const { data } = await createClient().auth.getSession()
      if (active.current !== turn) return
      if (!data.session?.access_token) throw new Error("Sign in again to continue this inquiry.")
      const { language, llmConfig } = callbacks.current
      const config = llmConfig?.provider === "google" || llmConfig?.provider === "groq" ? llmConfig : undefined
      ws.send(JSON.stringify({
        ...turn.body, requestId: turn.id, courseId, sessionId, language,
        accessToken: data.session.access_token, ...config,
      }))
      turn.sent = true
    }).catch((cause: unknown) => { if (active.current === turn) fail(cause) })
  }, [connection, courseId, ensureSocket, fail, recoveryKey, sessionId, waitForTurn])

  const startTurn = useCallback((body: Turn["body"], display?: string, requestId?: string) => {
    start({ id: requestId ?? crypto.randomUUID(), body, display, sequence: 0, sent: false }, false)
  }, [start])

  const stop = useCallback(() => {
    const turn = active.current
    if (!turn) return
    if (turn.sent && socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify({ action: "cancel", requestId: turn.id }))
      setProgress("Stopping generation.")
      return
    }
    finish(true, "Generation stopped.")
  }, [finish])

  const sendMessage = useCallback(({ text, displayText, mode = "socratic", notebook, continuation }: ChatMessageRequest) => {
    const message = text.trim()
    if (!message) return
    const display = displayText?.trim() ? displayText.trim().slice(0, 500) : message
    startTurn({ message, ...(displayText?.trim() ? { displayText: display } : {}), mode, ...(notebook ? { notebook } : {}),
      ...(continuation ? { continueCourseFrom: continuation.from } : {}) }, display, continuation?.requestId)
  }, [startTurn])

  const runUnitAction = useCallback((from: string, command: UnitAction, label: string) => {
    const { action, logical_id, request_id } = command
    if (command.disabled || !from || !request_id || !logical_id ||
      (action !== "continue_learning" && action !== "deepen_unit")) return
    const displayText = label.trim().slice(0, 500)
    if (!displayText) return
    startTurn({ action, mode: "explain", fromRequestId: from, displayText,
      ...(action === "deepen_unit" ? { unitId: logical_id } : {}) }, displayText, request_id)
  }, [startTurn])

  const regenerate = useCallback(() => {
    const previous = last.current
    if (!previous || active.current) return
    if (retryable.current) {
      start({ ...previous, sequence: 0, sent: false }, true)
    } else if (!previous.body.action && !previous.body.continueCourseFrom) {
      startTurn(previous.body, previous.display)
    }
  }, [start, startTurn])

  const submitAttempt = useCallback(({ exerciseId, answer, hintsUsed }: { exerciseId: string; answer: string; hintsUsed: number }) => {
    const trimmed = answer.trim()
    if (!trimmed || !exerciseId) return
    let display = trimmed
    try {
      const decoded: unknown = JSON.parse(trimmed)
      if (Array.isArray(decoded) && decoded.every((value) => typeof value === "string")) {
        display = decoded.map((value, index) => `Blank ${index + 1}: ${value}`).join("\n")
      }
    } catch {
      // Plain-text answers are valid.
    }
    startTurn({ action: "submit_attempt", exerciseId, answer: trimmed, displayText: display, hintsUsed, mode: "exercise" }, display)
  }, [startTurn])

  const revealSolution = useCallback((exerciseId: string) => {
    if (exerciseId) startTurn({ action: "reveal_solution", exerciseId, mode: "exercise" })
  }, [startTurn])

  const restoreExercise = useCallback(() => {
    startTurn({ action: "restore_exercise", mode: "exercise" })
  }, [startTurn])

  const disconnect = useCallback(() => {
    const ws = socket.current
    socket.current = null
    ready.current = null
    if (ws && ws.readyState !== WebSocket.CLOSED) ws.close(1000)
    finish(false)
    setConnection("Disconnected")
  }, [finish])

  useEffect(() => {
    let retries = 0
    let retryTimer: ReturnType<typeof setTimeout>
    const connect = () => {
      void ensureSocket().then(() => { retries = 0 }).catch(() => {})
    }
    reconnect.current = () => {
      if (retries >= 3) return
      clearTimeout(retryTimer)
      retryTimer = setTimeout(connect, 1_000 * 2 ** retries++)
    }
    retryTimer = setTimeout(connect, 0)
    return () => {
      reconnect.current = null
      clearTimeout(retryTimer)
      clearTimeout(timeout.current)
      if (frame.current) cancelAnimationFrame(frame.current)
      frame.current = 0
      buffer.current = ""
      active.current = null
      last.current = null
      const ws = socket.current
      socket.current = null
      ready.current = null
      if (ws && ws.readyState !== WebSocket.CLOSED) ws.close(1000)
    }
  }, [ensureSocket])

  useEffect(() => {
    if (!recoverInterrupted) return
    const timer = setTimeout(() => {
      if (active.current || last.current) return
      try {
        const raw = sessionStorage.getItem(recoveryKey)
        if (!raw) return
        const saved = JSON.parse(raw) as Partial<Turn>
        if (typeof saved.id !== "string" || !saved.body || typeof saved.display !== "string") return
        last.current = { id: saved.id, body: saved.body, display: saved.display, sequence: 0, sent: false }
        retryable.current = true
        const mode = saved.body.mode
        setInterrupted({ text: saved.display, mode: mode === "exercise" || mode === "explain" ? mode : "socratic" })
        setProgress("Recover the last request.")
        setCanRegenerate(true)
      } catch { /* An invalid recovery record does not block chat. */ }
    }, 0)
    return () => clearTimeout(timer)
  }, [recoverInterrupted, recoveryKey])

  return { messages, explanationTurns, explanationUnits, status, progress, connection, stop, error, sendMessage, runUnitAction, submitAttempt, revealSolution,
    restoreExercise, setMessages, regenerate, canRegenerate, interrupted, disconnect }
}
