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
import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react"
import type { UIMessage } from "ai"
import { createClient } from "@/lib/supabase/client"
import {
  buildChatWsUrl,
  parseServerMessage,
  type DiagnosticReport,
  type EvaluationResult,
  type LearningMode,
  type PublicCorrection,
  type PublicExercise,
  type PublicExplanation,
  type PublicSolution,
} from "@/lib/socra-ws"

// Mirrors the @ai-sdk/react `useChat` status union so existing UI (ChatInput,
// ChatPanel, MessageList) works unchanged — including the "ready" idle state.
export type ChatStatus = "ready" | "connecting" | "submitted" | "streaming" | "error"

interface UseSocraChatOpts {
  sessionId: string
  courseId: string
  /** Optional per-request LLM config from the Settings dialog. Google and Groq
   *  are forwarded to the backend; other providers are not yet supported there. */
  llmConfig?: { apiKey?: string; provider?: string; model?: string }
  language: "fr" | "en"
  onDiagnostic?: (d: DiagnosticReport) => void
  onContext?: (e: EvaluationResult) => void
  onExercise?: (e: PublicExercise) => void
  onExplanation?: (e: PublicExplanation) => void
  onCorrection?: (e: PublicCorrection) => void
  onSolution?: (e: PublicSolution) => void
  onError?: (err: Error) => void
}

interface UseSocraChatReturn {
  messages: UIMessage[]
  status: ChatStatus
  progress: string
  error: Error | null
  sendMessage: (m: { text: string; displayText?: string; mode?: LearningMode }) => void
  submitAttempt: (attempt: { exerciseId: string; answer: string; hintsUsed: number }) => void
  revealSolution: (exerciseId: string) => void
  restoreExercise: () => void
  setMessages: Dispatch<SetStateAction<UIMessage[]>>
  regenerate: () => void
  /** Force-close the underlying socket. Mostly useful for tests. */
  disconnect: () => void
}

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID()
  }
  return `m_${Date.now()}_${Math.random().toString(36).slice(2)}`
}

function makeUserMessage(text: string): UIMessage {
  return {
    id: newId(),
    role: "user",
    parts: [{ type: "text", text }],
  } as UIMessage
}

function makeAssistantStub(): UIMessage {
  return {
    id: newId(),
    role: "assistant",
    parts: [{ type: "text", text: "" }],
  } as UIMessage
}

function appendToLastAssistantText(messages: UIMessage[], chunk: string): UIMessage[] {
  if (messages.length === 0) return messages
  const last = messages[messages.length - 1]
  if (last.role !== "assistant") return messages

  const newParts = last.parts.map((p, i) => {
    if (i === 0 && p.type === "text") {
      return { ...p, text: (p.text ?? "") + chunk }
    }
    return p
  })
  return [...messages.slice(0, -1), { ...last, parts: newParts } as UIMessage]
}

function attachAssistantMetadata(messages: UIMessage[], key: string, value: unknown): UIMessage[] {
  const index = messages.findLastIndex((message) => message.role === "assistant")
  if (index < 0) return messages
  const next = [...messages]
  const target = next[index] as UIMessage & { metadata?: Record<string, unknown> }
  next[index] = { ...target, metadata: { ...target.metadata, [key]: value } } as UIMessage
  return next
}

export function useSocraChat(opts: UseSocraChatOpts): UseSocraChatReturn {
  const { sessionId, courseId, llmConfig, language, onDiagnostic, onContext, onExercise, onExplanation, onCorrection, onSolution, onError } = opts

  const [messages, setMessages] = useState<UIMessage[]>([])
  // Start in "ready" so the chat input is enabled right away — the WS only
  // opens lazily when the user actually sends a message.
  const [status, setStatus] = useState<ChatStatus>("ready")
  const [progress, setProgress] = useState("")
  const [error, setError] = useState<Error | null>(null)

  const socketRef = useRef<WebSocket | null>(null)
  const lastUserTextRef = useRef<string>("")
  const lastDisplayTextRef = useRef<string>("")
  const lastModeRef = useRef<LearningMode>("socratic")
  const pendingMessageRef = useRef<{ text: string; displayText: string; mode: LearningMode } | null>(null)
  const turnInFlightRef = useRef(false)
  // Refs to avoid recreating the WS handlers on every render.
  const onDiagnosticRef = useRef(onDiagnostic)
  const onContextRef = useRef(onContext)
  const onExerciseRef = useRef(onExercise)
  const onExplanationRef = useRef(onExplanation)
  const onCorrectionRef = useRef(onCorrection)
  const onSolutionRef = useRef(onSolution)
  const onErrorRef = useRef(onError)
  const llmConfigRef = useRef(llmConfig)
  useEffect(() => { onDiagnosticRef.current = onDiagnostic }, [onDiagnostic])
  useEffect(() => { onContextRef.current = onContext }, [onContext])
  useEffect(() => { onExerciseRef.current = onExercise }, [onExercise])
  useEffect(() => { onExplanationRef.current = onExplanation }, [onExplanation])
  useEffect(() => { onCorrectionRef.current = onCorrection }, [onCorrection])
  useEffect(() => { onSolutionRef.current = onSolution }, [onSolution])
  useEffect(() => { onErrorRef.current = onError }, [onError])
  useEffect(() => { llmConfigRef.current = llmConfig }, [llmConfig])

  // ---------------------------------------------------------------------
  // Socket lifecycle: open lazily on first sendMessage, close on unmount.
  // ---------------------------------------------------------------------
  const ensureSocket = useCallback((): Promise<WebSocket> => {
    return new Promise((resolve, reject) => {
      const existing = socketRef.current
      if (existing && existing.readyState === WebSocket.OPEN) {
        resolve(existing)
        return
      }
      if (existing && existing.readyState === WebSocket.CONNECTING) {
        existing.addEventListener("open", () => resolve(existing), { once: true })
        existing.addEventListener("error", () => reject(new Error("WebSocket failed to open")), { once: true })
        return
      }

      setStatus("connecting")
      let ws: WebSocket
      try {
        ws = new WebSocket(buildChatWsUrl(sessionId))
      } catch (err) {
        const e = err instanceof Error ? err : new Error("Failed to construct WebSocket")
        setStatus("error")
        setError(e)
        onErrorRef.current?.(e)
        reject(e)
        return
      }

      socketRef.current = ws

      ws.addEventListener("open", () => {
        resolve(ws)
      }, { once: true })

      ws.addEventListener("error", () => {
        const e = new Error("WebSocket error — is the backend running?")
        setStatus("error")
        setError(e)
        onErrorRef.current?.(e)
        reject(e)
      })

      ws.addEventListener("close", () => {
        // Only mark error if a turn was in flight; otherwise just go idle.
        setStatus((prev) => (prev === "streaming" || prev === "submitted" ? "error" : prev))
      })

      ws.addEventListener("message", (ev) => {
        const msg = parseServerMessage(typeof ev.data === "string" ? ev.data : "")
        if (!msg) return

        switch (msg.type) {
          case "diagnostic": {
            onDiagnosticRef.current?.(msg.content)
            break
          }
          case "token": {
            const chunk = msg.content
            if (!chunk) break
            setStatus("streaming")
            setMessages((prev) => {
              // Promote the assistant placeholder once the first token arrives.
              const last = prev[prev.length - 1]
              if (!last || last.role !== "assistant") {
                return [...prev, { id: newId(), role: "assistant", parts: [{ type: "text", text: chunk }] } as UIMessage]
              }
              return appendToLastAssistantText(prev, chunk)
            })
            break
          }
          case "context": {
            onContextRef.current?.(msg.content)
            break
          }
          case "exercise": {
            onExerciseRef.current?.(msg.content)
            setMessages((prev) => attachAssistantMetadata(prev, "exercise", msg.content))
            setStatus("streaming")
            break
          }
          case "explanation": {
            onExplanationRef.current?.(msg.content)
            setMessages((prev) => attachAssistantMetadata(prev, "explanation", msg.content))
            setStatus("streaming")
            break
          }
          case "correction": {
            onCorrectionRef.current?.(msg.content)
            setMessages((prev) => attachAssistantMetadata(prev, "correction", msg.content))
            setStatus("streaming")
            break
          }
          case "solution": {
            onSolutionRef.current?.(msg.content)
            break
          }
          case "done": {
            turnInFlightRef.current = false
            setProgress("")
            setStatus("ready")
            break
          }
          case "progress": {
            setProgress(msg.content.stage)
            break
          }
          case "error": {
            turnInFlightRef.current = false
            setProgress("")
            const content = msg.content
            const e = new Error(typeof content === "string" ? content || "Backend error" : content.message)
            if (typeof content !== "string") Object.assign(e, { code: content.code })
            setStatus("error")
            setError(e)
            onErrorRef.current?.(e)
            break
          }
        }
      })
    })
  }, [sessionId])

  // ---------------------------------------------------------------------
  // Public actions
  // ---------------------------------------------------------------------
  const sendMessage = useCallback(
    (m: { text: string; displayText?: string; mode?: LearningMode }) => {
      const text = (m.text ?? "").trim()
      if (!text || turnInFlightRef.current) return
      turnInFlightRef.current = true
      const mode = m.mode ?? "socratic"
      const displayText = (m.displayText ?? text).trim().slice(0, 500) || text.slice(0, 500)
      setError(null)
      setProgress(mode === "explain" ? "Reviewing your course material…" : mode === "exercise" ? "Finding relevant course material…" : "Connecting to your tutor…")
      lastUserTextRef.current = text
      lastDisplayTextRef.current = displayText
      lastModeRef.current = mode
      pendingMessageRef.current = { text, displayText, mode }
      setStatus("submitted")
      setMessages((prev) => [...prev, makeUserMessage(displayText), makeAssistantStub()])

      ensureSocket()
        .then(async (ws) => {
          const pending = pendingMessageRef.current
          if (pending == null) return
          pendingMessageRef.current = null
          const cfg = llmConfigRef.current
          // Only forward keys for providers supported by the Python backend.
          const forwardKey = cfg?.provider === "google" || cfg?.provider === "groq" ? cfg : undefined
          let accessToken: string | undefined
          if (pending.mode === "exercise" || pending.mode === "explain") {
            const { data, error: authError } = await createClient().auth.getSession()
            if (authError || !data.session?.access_token) {
              throw new Error("Sign in again before requesting course-based practice.")
            }
            accessToken = data.session.access_token
          }
          ws.send(
            JSON.stringify({
              message: pending.text,
              ...(pending.displayText !== pending.text ? { displayText: pending.displayText } : {}),
              courseId,
              sessionId,
              mode: pending.mode,
              language,
              ...(accessToken ? { accessToken } : {}),
              ...(forwardKey?.apiKey ? { apiKey: forwardKey.apiKey } : {}),
              ...(forwardKey?.provider ? { provider: forwardKey.provider } : {}),
              ...(forwardKey?.model ? { model: forwardKey.model } : {}),
            })
          )
        })
        .catch((err: unknown) => {
          turnInFlightRef.current = false
          const e = err instanceof Error ? err : new Error("Could not send your message")
          setStatus("error")
          setError(e)
          onErrorRef.current?.(e)
        })
    },
    [courseId, sessionId, language, ensureSocket]
  )

  const regenerate = useCallback(() => {
    const last = lastUserTextRef.current
    if (!last) return
    // Trim the last assistant turn (if any) before resending.
    setMessages((prev) => {
      if (prev.length === 0) return prev
      const tail = prev[prev.length - 1]
      return tail.role === "assistant" ? prev.slice(0, -1) : prev
    })
    sendMessage({ text: last, displayText: lastDisplayTextRef.current, mode: lastModeRef.current })
  }, [sendMessage])

  const submitAttempt = useCallback(
    ({ exerciseId, answer, hintsUsed }: { exerciseId: string; answer: string; hintsUsed: number }) => {
      const trimmed = answer.trim()
      if (!trimmed || !exerciseId || turnInFlightRef.current) return
      let displayAnswer = trimmed
      try {
        const decoded: unknown = JSON.parse(trimmed)
        if (Array.isArray(decoded) && decoded.every((value) => typeof value === "string")) {
          displayAnswer = decoded.map((value, index) => `Blank ${index + 1}: ${value}`).join("\n")
        }
      } catch {
        // Existing short-answer submissions are plain text.
      }
      turnInFlightRef.current = true
      setError(null)
      setProgress("Reviewing your answer…")
      setStatus("submitted")
      setMessages((prev) => [...prev, makeUserMessage(displayAnswer), makeAssistantStub()])
      ensureSocket()
        .then(async (ws) => {
          const { data, error: authError } = await createClient().auth.getSession()
          if (authError || !data.session?.access_token) {
            throw new Error("Sign in again before submitting an answer.")
          }
          const cfg = llmConfigRef.current
          const forwardKey = cfg?.provider === "google" || cfg?.provider === "groq" ? cfg : undefined
          ws.send(JSON.stringify({
            action: "submit_attempt",
            exerciseId,
            answer: trimmed,
            ...(displayAnswer !== trimmed ? { displayText: displayAnswer } : {}),
            hintsUsed,
            courseId,
            sessionId,
            mode: "exercise",
            language,
            accessToken: data.session.access_token,
            ...(forwardKey?.apiKey ? { apiKey: forwardKey.apiKey } : {}),
            ...(forwardKey?.provider ? { provider: forwardKey.provider } : {}),
            ...(forwardKey?.model ? { model: forwardKey.model } : {}),
          }))
        })
        .catch((err: unknown) => {
          turnInFlightRef.current = false
          const e = err instanceof Error ? err : new Error("Could not submit your answer")
          setStatus("error")
          setError(e)
          onErrorRef.current?.(e)
        })
    },
    [courseId, sessionId, language, ensureSocket]
  )

  const revealSolution = useCallback(
    (exerciseId: string) => {
      if (!exerciseId || turnInFlightRef.current) return
      turnInFlightRef.current = true
      setError(null)
      setStatus("submitted")
      ensureSocket()
        .then(async (ws) => {
          const { data, error: authError } = await createClient().auth.getSession()
          if (authError || !data.session?.access_token) {
            throw new Error("Sign in again before revealing the solution.")
          }
          ws.send(JSON.stringify({
            action: "reveal_solution",
            exerciseId,
            courseId,
            sessionId,
            mode: "exercise",
            accessToken: data.session.access_token,
          }))
        })
        .catch((err: unknown) => {
          turnInFlightRef.current = false
          const e = err instanceof Error ? err : new Error("Could not reveal the solution")
          setStatus("error")
          setError(e)
          onErrorRef.current?.(e)
        })
    },
    [courseId, sessionId, ensureSocket]
  )

  const restoreExercise = useCallback(() => {
    setError(null)
    setStatus("submitted")
    ensureSocket()
      .then(async (ws) => {
        const { data, error: authError } = await createClient().auth.getSession()
        if (authError || !data.session?.access_token) {
          throw new Error("Sign in again to restore this exercise.")
        }
        ws.send(JSON.stringify({
          action: "restore_exercise",
          courseId,
          sessionId,
          mode: "exercise",
          accessToken: data.session.access_token,
        }))
      })
      .catch((err: unknown) => {
        const e = err instanceof Error ? err : new Error("Could not restore the exercise")
        setStatus("error")
        setError(e)
        onErrorRef.current?.(e)
      })
  }, [courseId, sessionId, ensureSocket])

  const disconnect = useCallback(() => {
    const ws = socketRef.current
    if (ws && ws.readyState !== WebSocket.CLOSED) ws.close(1000, "client disconnect")
    socketRef.current = null
    setStatus("ready")
  }, [])

  // Close socket when the consumer unmounts (e.g. navigating away).
  useEffect(() => {
    return () => {
      const ws = socketRef.current
      if (ws && ws.readyState !== WebSocket.CLOSED) ws.close(1000, "unmount")
      socketRef.current = null
    }
  }, [])

  return {
    messages,
    status,
    progress,
    error,
    sendMessage,
    submitAttempt,
    revealSolution,
    restoreExercise,
    setMessages,
    regenerate,
    disconnect,
  }
}
