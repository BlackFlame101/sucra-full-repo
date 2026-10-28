// Re-export database types for convenience
export type {
  Database,
  Tables,
  TablesInsert,
  TablesUpdate,
  Json,
} from "./database"

// Type aliases using Supabase generated types
import type { Tables, TablesInsert, TablesUpdate } from "./database"

export type Course = Tables<"courses">
export type CourseInsert = TablesInsert<"courses">
export type CourseUpdate = TablesUpdate<"courses">

export type Document = Tables<"documents">
export type DocumentInsert = TablesInsert<"documents">
export type DocumentUpdate = TablesUpdate<"documents">

export type Embedding = Tables<"embeddings">
export type EmbeddingInsert = TablesInsert<"embeddings">
export type EmbeddingUpdate = TablesUpdate<"embeddings">

export type Session = Tables<"sessions">
export type CourseSession = Session & {
  exam_id?: string
  exam_status?: "in_progress" | "completed"
}
export type SessionInsert = TablesInsert<"sessions">
export type SessionUpdate = TablesUpdate<"sessions">

export type Message = Tables<"messages">
export type MessageInsert = TablesInsert<"messages">
export type MessageUpdate = TablesUpdate<"messages">

export type KeyTerm = Tables<"key_terms">
export type KeyTermInsert = TablesInsert<"key_terms">
export type KeyTermUpdate = TablesUpdate<"key_terms">

// Application-specific types
export interface ContextData {
  keyTerms: string[]
  suggestedReadings: SuggestedReading[]
}

export interface SuggestedReading {
  documentId: string
  documentName: string
  pageNumber: number
  section: string
  relevance: number
}

// RAG match result type (from match_embeddings function)
export interface EmbeddingMatch {
  id: string
  content: string
  document_id: string
  page_number: number
  chunk_index: number
  filename: string
  similarity: number
}
