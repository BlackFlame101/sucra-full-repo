import type { ExerciseCitation } from "@/lib/socra-ws"

export interface ExamQuestion {
  id: string
  exercise_type: "short_answer" | "multiple_choice" | "numerical" | "code" | "sql"
  concept: string
  difficulty: "beginner" | "intermediate" | "advanced"
  bloom_level: string
  prompt: string
  citations: ExerciseCitation[]
  choices: Array<{ id: string; text: string }>
  numeric_unit: string
  code_language: string
  code_task_mode?: "completion" | "write"
  starter_code: string
  sql_setup: string[]
}

export interface ExamResult {
  exercise_id: string
  exercise_type: ExamQuestion["exercise_type"]
  difficulty?: ExamQuestion["difficulty"]
  code_task_mode?: "completion" | "write"
  code_language?: string
  code_expected_answers?: string[]
  completed_code?: string
  concept: string
  prompt: string
  answer: string
  expected_answer?: string
  score: number
  max_score: number
  feedback: string
  criterion_feedback: Array<{
    criterion: string
    awarded_points: number
    possible_points: number
    feedback: string
  }>
  citations: ExerciseCitation[]
  next_step: string
}

export interface CourseExam {
  id: string
  status: "in_progress" | "completed"
  topic: string
  requested_types: ExamQuestion["exercise_type"][]
  questions: ExamQuestion[]
  answers: Record<string, string>
  results: ExamResult[]
  score: number | null
  max_score: number
}
