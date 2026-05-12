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
import {
  buildChatWsUrl,
  parseServerMessage,
  type DiagnosticReport,
  type EvaluationResult,
} from "@/lib/socra-ws"

// Mirrors the @ai-sdk/react `useChat` status union so existing UI (ChatInput,
// ChatPanel, MessageList) works unchanged — including the "ready" idle state.
export type ChatStatus = "ready" | "connecting" | "submitted" | "streaming" | "error"

interface UseSocraChatOpts {
  sessionId: string
  courseId: string
  /** Optional per-request LLM config from the Settings dialog. Only Google
   *  provider is forwarded to the backend; others are silently ignored. */
  llmConfig?: { apiKey?: string; provider?: string; model?: string }
  onDiagnostic?: (d: DiagnosticReport) => void
  onContext?: (e: EvaluationResult) => void
  onError?: (err: Error) => void
}

interface UseSocraChatReturn {
  messages: UIMessage[]
  status: ChatStatus
  error: Error | null
  sendMessage: (m: { text: string }) => void
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

export function useSocraChat(opts: UseSocraChatOpts): UseSocraChatReturn {
  const { sessionId, courseId, llmConfig, onDiagnostic, onContext, onError } = opts

  const [messages, setMessages] = useState<UIMessage[]>([])
  // Start in "ready" so the chat input is enabled right away — the WS only
  // opens lazily when the user actually sends a message.
  const [status, setStatus] = useState<ChatStatus>("ready")
  const [error, setError] = useState<Error | null>(null)

  const socketRef = useRef<WebSocket | null>(null)
  const lastUserTextRef = useRef<string>("")
  const pendingMessageRef = useRef<string | null>(null)
  // Refs to avoid recreating the WS handlers on every render.
  const onDiagnosticRef = useRef(onDiagnostic)
  const onContextRef = useRef(onContext)
  const onErrorRef = useRef(onError)
  const llmConfigRef = useRef(llmConfig)
  useEffect(() => { onDiagnosticRef.current = onDiagnostic }, [onDiagnostic])
  useEffect(() => { onContextRef.current = onContext }, [onContext])
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
          case "done": {
            setStatus("ready")
            break
          }
          case "error": {
            const e = new Error(msg.content || "Backend error")
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
    (m: { text: string }) => {
      const text = (m.text ?? "").trim()
      if (!text) return
      setError(null)
      lastUserTextRef.current = text
      pendingMessageRef.current = text
      setStatus("submitted")
      setMessages((prev) => [...prev, makeUserMessage(text), makeAssistantStub()])

      ensureSocket()
        .then((ws) => {
          const pending = pendingMessageRef.current
          if (pending == null) return
          pendingMessageRef.current = null
          const cfg = llmConfigRef.current
          // Only forward the key if the user picked the Google provider —
          // the backend ignores anything else, so we strip it client-side
          // to avoid sending OpenAI/Anthropic keys over the wire.
          const forwardKey = cfg?.provider === "google" ? cfg : undefined
          ws.send(
            JSON.stringify({
              message: pending,
              courseId,
              sessionId,
              ...(forwardKey?.apiKey ? { apiKey: forwardKey.apiKey } : {}),
              ...(forwardKey?.provider ? { provider: forwardKey.provider } : {}),
              ...(forwardKey?.model ? { model: forwardKey.model } : {}),
            })
          )
        })
        .catch(() => {
          // ensureSocket already updated status/error.
        })
    },
    [courseId, sessionId, ensureSocket]
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
    sendMessage({ text: last })
  }, [sendMessage])

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
    error,
    sendMessage,
    setMessages,
    regenerate,
    disconnect,
  }
}
