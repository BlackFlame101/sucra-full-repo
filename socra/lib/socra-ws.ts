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
  page_number: number
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

export type LearningMode = "socratic" | "exercise" | "explain"

export interface PublicExplanation {
  definition: string
  intuition: string
  sections?: Array<{ heading: string; content: string; code?: string; code_language?: string; walkthrough?: Array<{ code: string; explanation: string }> }>
  course_example: string
  common_pitfalls: string[]
  citations: ExerciseCitation[]
  check_question: string
}

export interface ExerciseCitation {
  document_id: string
  filename: string
  page_number: number | null
  excerpt: string
}

/** Pre-attempt exercise fields only; never add answer or rubric here. */
export interface PublicExercise {
  id: string
  exercise_type: "short_answer" | "multiple_choice" | "numerical" | "code" | "sql"
  concept: string
  difficulty: "beginner" | "intermediate" | "advanced"
  bloom_level: "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create"
  prompt: string
  citations: ExerciseCitation[]
  hints: string[]
  choices: Array<{ id: string; text: string }>
  numeric_unit: string
  code_language: string
    code_task_mode?: "completion" | "write"
  starter_code: string
  sql_setup: string[]
}

export interface PublicCorrection {
  attempt_id: string
  total_score: number
  max_score: number
  overall_feedback: string
  error_category: "correct" | "partial" | "conceptual" | "incomplete" | "off_topic"
  criterion_feedback: Array<{
    criterion: string
    awarded_points: number
    possible_points: number
    feedback: string
  }>
  citations: ExerciseCitation[]
  next_step: string
  hints_used: number
}

export interface PublicSolution {
  exercise_id: string
  expected_answer: string
  common_mistakes: string[]
}

export type WSServerMessage =
  | { type: "diagnostic"; content: DiagnosticReport }
  | { type: "token"; content: string }
  | { type: "context"; content: EvaluationResult }
  | { type: "exercise"; content: PublicExercise }
  | { type: "correction"; content: PublicCorrection }
  | { type: "solution"; content: PublicSolution }
  | { type: "explanation"; content: PublicExplanation }
  | { type: "progress"; content: { stage: string } }
  | { type: "done" }
  | { type: "error"; content: string | { code: string; message: string } }

// ---------------------------------------------------------------------------
// Client → server message shape
// ---------------------------------------------------------------------------

export interface WSClientMessage {
  message?: string
  courseId: string
  sessionId: string
  /** Optional per-request overrides — currently Google Gemini or Groq. */
  apiKey?: string
  provider?: string
  model?: string
  mode?: LearningMode
  accessToken?: string
  action?: "message" | "submit_attempt" | "reveal_solution"
  exerciseId?: string
  answer?: string
  hintsUsed?: number
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
