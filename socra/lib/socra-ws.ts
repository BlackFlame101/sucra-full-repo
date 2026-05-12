/**
 * Typed message contracts and helpers for the Socra Python backend WebSocket.
 *
 * Endpoint: `ws://<BACKEND_HOST>/ws/chat/{sessionId}`
 *
 * Protocol mirrors `socra-backend/api/websocket.py`.
 */

// ---------------------------------------------------------------------------
// Server → client message shapes
// ---------------------------------------------------------------------------

export interface DiagnosticReport {
  topic: string
  initial_level: "beginner" | "intermediate" | "advanced"
  identified_gaps: string[]
  prerequisite_concepts: string[]
  first_socratic_question: string
}

export interface SuggestedReadingItem {
  document_id: string | null
  filename: string | null
  page_number: number | null
  excerpt: string
  similarity: number | null
}

export interface EvaluationResult {
  comprehension_score: number
  misconceptions: string[]
  concepts_understood: string[]
  key_terms: string[]
  suggested_readings: SuggestedReadingItem[]
  next_micro_objective: string
}

export type WSServerMessage =
  | { type: "diagnostic"; content: DiagnosticReport }
  | { type: "token"; content: string }
  | { type: "context"; content: EvaluationResult }
  | { type: "done" }
  | { type: "error"; content: string }

// ---------------------------------------------------------------------------
// Client → server message shape
// ---------------------------------------------------------------------------

export interface WSClientMessage {
  message: string
  courseId: string
  sessionId: string
  /** Optional per-request overrides — only honoured for provider === "google". */
  apiKey?: string
  provider?: string
  model?: string
}

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

/** Resolve the WS base URL, with a sensible localhost fallback. */
export function getBackendWsUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_BACKEND_WS_URL
  if (fromEnv && fromEnv.length > 0) return fromEnv.replace(/\/+$/, "")
  return "ws://localhost:8000"
}

export function buildChatWsUrl(sessionId: string): string {
  return `${getBackendWsUrl()}/ws/chat/${encodeURIComponent(sessionId)}`
}

// ---------------------------------------------------------------------------
// Mapping: backend SuggestedReadingItem → frontend ContextPanel reading shape
// ---------------------------------------------------------------------------

export interface ContextPanelReading {
  documentName: string
  pageNumber: number
  section: string
  chapter?: string
}

/**
 * The existing `SuggestedReading` UI expects `{ documentName, pageNumber, section, chapter? }`.
 * The backend produces `{ filename, page_number, excerpt, ... }`.
 * This adapter keeps the design 100% intact.
 */
export function adaptSuggestedReading(
  item: SuggestedReadingItem
): ContextPanelReading {
  const excerpt = (item.excerpt || "").trim()
  const section =
    excerpt.length > 80 ? excerpt.slice(0, 80).trimEnd() + "…" : excerpt || "Relevant excerpt"
  return {
    documentName: item.filename || "Course material",
    pageNumber: item.page_number ?? 0,
    section,
  }
}

export function adaptSuggestedReadings(
  items: SuggestedReadingItem[] | undefined | null
): ContextPanelReading[] {
  if (!items || items.length === 0) return []
  return items.map(adaptSuggestedReading)
}

// ---------------------------------------------------------------------------
// Safe JSON parse
// ---------------------------------------------------------------------------

export function parseServerMessage(raw: string): WSServerMessage | null {
  try {
    const obj = JSON.parse(raw) as Partial<WSServerMessage> & { type?: string }
    if (!obj || typeof obj !== "object" || typeof obj.type !== "string") return null
    return obj as WSServerMessage
  } catch {
    return null
  }
}
