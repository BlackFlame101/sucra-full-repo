/**
 * Typed message contracts and helpers for the Socra Python backend WebSocket.
 *
 * Endpoint: `ws://<BACKEND_HOST>/ws/chat/{sessionId}`
 *
 * Protocol mirrors `socra-backend/api/websocket.py`.
 */

import { isExplanationEventType, validExplanationEvent, type ExplanationEvent } from "./explanation-v2"
import { isEducationalDocument, type EducationalDocument } from "./educational-document"

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
export type NotebookAction = "ask" | "related" | "improve" | "expand" | "simplify" | "example" | "summarize" | "correct" | "flashcards" | "quiz"
export type NotebookContext = { id: string; action: NotebookAction; selection?: string }

export interface PublicExplanation {
  presentation?: "brief" | "standard" | "walkthrough" | "beginner" | "revision_sheet" | "full_course"
  language?: string
  course_progress?: CourseProgress
  coverage_notices?: { heading: string; content: string }[]
  definition: string
  intuition: string
  sections?: ExplanationSection[]
  course_example: string
  common_pitfalls: string[]
  citations: ExerciseCitation[]
  check_question: string
}

export type ExplanationPayload = PublicExplanation | EducationalDocument

export interface CourseProgress {
  part: number
  total_parts: number
  request_id: string | null
  next_request_id: string | null
  language: string
  inventory_uncertain: boolean
  generated_parts?: Array<{ part: number; request_id: string | null }>
  sections: Array<{ id: string; title: string; start: number; end: number; part: number
    status: "covered" | "partial" | "missing" | "unverifiable" | "not_yet_generated" }>
}

export interface ExplanationSection {
  heading: string
  content: string
  code?: string
  code_language?: string
  walkthrough?: Array<{ code: string; explanation: string }>
  citations?: ExerciseCitation[] | null
  covers?: string[] | null
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

export type PublicCard =
  | { kind: "exercise"; card: PublicExercise }
  | { kind: "correction"; card: PublicCorrection }
  | { kind: "solution"; card: PublicSolution }
  | { kind: "explanation"; card: ExplanationPayload }

export type WSServerMessage =
  | ExplanationEvent
  | { type: "document_snapshot"; content: EducationalDocument }
  | { type: "diagnostic"; content: DiagnosticReport }
  | { type: "token"; content: string }
  | { type: "content_delta"; content: { text: string | null; preview?: boolean } }
  | { type: "card_ready"; content: PublicCard }
  | { type: "context_update"; content: EvaluationResult }
  | { type: "connected" | "request_accepted" | "turn_finalized" | "cancelled" }
  | { type: "response_complete"; content: { message_id?: string; text: string } }
  | { type: "context"; content: EvaluationResult }
  | { type: "exercise"; content: PublicExercise }
  | { type: "correction"; content: PublicCorrection }
  | { type: "solution"; content: PublicSolution }
  | { type: "explanation"; content: ExplanationPayload }
  | { type: "progress"; content: { stage: string } }
  | { type: "done" }
  | { type: "error"; content: string | { code: string; message: string } }

// ---------------------------------------------------------------------------
// Client → server message shape
// ---------------------------------------------------------------------------

export interface WSClientMessage {
  requestId?: string
  version?: 2
  message?: string
  courseId: string
  sessionId: string
  /** Optional per-request overrides — currently Google Gemini or Groq. */
  apiKey?: string
  provider?: string
  model?: string
  mode?: LearningMode
  accessToken?: string
  action?: "authenticate" | "message" | "submit_attempt" | "reveal_solution" | "restore_exercise" | "cancel"
    | "continue_learning" | "deepen_unit"
  fromRequestId?: string
  unitId?: string
  displayText?: string
  exerciseId?: string
  answer?: string
  hintsUsed?: number
  notebook?: NotebookContext
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
  documentId?: string
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
    documentId: item.document_id ?? undefined,
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

export function parseServerMessage(raw: string): (WSServerMessage & { request_id?: string; session_id?: string; sequence?: number; version?: number }) | null {
  try {
    const obj = JSON.parse(raw) as Partial<WSServerMessage> & { type?: string }
    if (!obj || typeof obj !== "object" || typeof obj.type !== "string") return null
    if (isExplanationEventType(obj.type)) {
      const envelope = obj as { request_id?: unknown; session_id?: unknown; content?: unknown }
      if (typeof envelope.request_id !== "string" || typeof envelope.session_id !== "string"
          || !validExplanationEvent(obj.type, envelope.content)) return null
    }
    if (obj.type === "token" && (!("content" in obj) || typeof obj.content !== "string")) return null
    if (obj.type === "document_snapshot" && !isEducationalDocument(obj.content)) return null
    if (obj.type === "content_delta" && (!obj.content || (obj.content.text !== null && typeof obj.content.text !== "string"))) return null
    if (obj.type === "card_ready" && (!obj.content?.card || !["exercise", "explanation", "correction", "solution"].includes(obj.content.kind))) return null
    if (obj.type === "response_complete" && (!("content" in obj) || typeof obj.content?.text !== "string")) return null
    return obj as WSServerMessage
  } catch {
    return null
  }
}
