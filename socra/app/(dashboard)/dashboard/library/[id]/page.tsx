"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { ArrowLeft, ArrowRight, Bookmark, LoaderCircle } from "lucide-react"
import { useParams } from "next/navigation"
import { ExerciseCard } from "@/components/chat/ExerciseCard"
import { ExerciseFeedbackCard } from "@/components/chat/ExerciseFeedbackCard"
import { ExplanationCard } from "@/components/chat/ExplanationCard"
import type { PublicCorrection, PublicExercise, PublicExplanation, PublicSolution } from "@/lib/socra-ws"
import { Button } from "@/components/ui/button"

type SavedMessage = { id: string; role: string; content: string; metadata?: Record<string, unknown> }
type SavedQuestion = { id: string; prompt: string; exercise_type: string; concept?: string }
type SavedExam = {
  topic?: string
  status?: string
  questions?: SavedQuestion[]
  answers?: Record<string, string>
  results?: Array<{ exercise_id: string; feedback: string; expected_answer?: string; score?: number; max_score?: number }>
  score?: number | null
  max_score?: number
}
type SavedLibraryItem = {
  id: string
  course_id: string
  title: string
  item_type: "explanation" | "exercise" | "inquiry" | "exam"
  course_name: string
  original_session_id: string | null
  created_at: string
  content: {
    snapshot?: { kind?: "inquiry" | "exam"; messages?: SavedMessage[]; exam?: SavedExam }
    explanation?: { definition?: string; intuition?: string; sections?: Array<{ heading?: string; content?: string; code?: string }>; course_example?: string }
    expected_answer?: string
    solution?: { expected_answer?: string; common_mistakes?: string[] }
    correction?: { overall_feedback?: string }
  }
}

export default function SavedLibraryItemPage() {
  const { id } = useParams<{ id: string }>()
  const [item, setItem] = useState<SavedLibraryItem | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(`/api/library/${encodeURIComponent(id)}`)
      .then(async (response) => {
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.error || "Could not open this saved item.")
        return payload as SavedLibraryItem
      })
      .then((savedItem) => { if (!cancelled) { setItem(savedItem); setError("") } })
      .catch((cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not open this saved item.") })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [id])

  const snapshot = item?.content.snapshot

  return <main className="container mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-12">
    <Link href="/dashboard/library" className="mb-8 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground">
      <ArrowLeft className="h-4 w-4" /> Back to Library
    </Link>

    {loading ? <div className="mt-8 flex items-center gap-3 text-sm text-muted-foreground"><LoaderCircle className="h-4 w-4 animate-spin" />Opening saved item…</div> : error ? <p role="alert" className="mt-8 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</p> : item ? <>
      <header className="mb-8 mt-6">
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-secondary/30 bg-secondary/10 px-3 py-1 text-xs font-medium uppercase tracking-wider text-secondary">
          <Bookmark className="h-3.5 w-3.5" /> Saved {snapshot?.kind ?? (item.item_type === "exercise" ? "answer" : item.item_type)} · {item.course_name}
        </div>
        <h1 className="font-serif text-3xl font-medium tracking-tight sm:text-4xl">{item.title}</h1>
        {snapshot?.kind === "exam" && item.content.snapshot?.exam?.topic && <p className="mt-2 text-muted-foreground">{item.content.snapshot.exam.topic}</p>}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">Saved {new Date(item.created_at).toLocaleDateString()}</p>
          {snapshot?.kind === "inquiry" && item.original_session_id && <Button asChild size="sm" className="gap-2"><Link href={`/dashboard/course/${item.course_id}/inquiry/${item.original_session_id}`}>Continue inquiry <ArrowRight className="h-4 w-4" /></Link></Button>}
          {snapshot?.kind === "exam" && item.original_session_id && <Button asChild size="sm" className="gap-2"><Link href={`/dashboard/course/${item.course_id}/exam/${item.original_session_id}?restore=1`}>Return to exam <ArrowRight className="h-4 w-4" /></Link></Button>}
        </div>
      </header>

      {snapshot?.kind === "inquiry" && <section aria-label="Saved inquiry transcript" className="space-y-4">
        {snapshot.messages?.length ? snapshot.messages.map((message) => {
          const metadata = message.metadata ?? {}
          const exercise = metadata.exercise as PublicExercise | undefined
          const correction = metadata.correction as PublicCorrection | undefined
          const solution = metadata.solution as PublicSolution | undefined
          const explanation = metadata.explanation as PublicExplanation | undefined
          return <div key={message.id} className="space-y-4">
            <article className={`rounded-2xl border p-4 sm:p-5 ${message.role === "user" ? "ml-6 border-secondary/25 bg-secondary/5 sm:ml-16" : "mr-6 border-border/60 bg-card/50 sm:mr-16"}`}>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{message.role === "user" ? "You" : "Socra"}</p>
              <p className="whitespace-pre-wrap text-sm leading-7">{message.content}</p>
            </article>
            {message.role === "assistant" && exercise && <ExerciseCard exercise={exercise} onNextExercise={() => {}} onSubmitAttempt={() => {}} readOnly />}
            {message.role === "assistant" && correction && <ExerciseFeedbackCard correction={correction} solution={solution ?? null} onRevealSolution={() => {}} onNextExercise={() => {}} readOnly />}
            {message.role === "assistant" && explanation && <ExplanationCard explanation={explanation} readOnly />}
          </div>
        }) : <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">This saved inquiry has no messages.</p>}
      </section>}

      {snapshot?.kind === "exam" && <section aria-label="Saved exam" className="space-y-5">
        <div className="rounded-2xl border border-secondary/25 bg-secondary/5 p-5">
          <p className="text-sm text-muted-foreground">{snapshot.exam?.status === "completed" ? "Final score" : "Exam status"}</p>
          <p className="mt-1 text-2xl font-medium">{snapshot.exam?.status === "completed" ? `${snapshot.exam.score ?? "—"} / ${snapshot.exam.max_score ?? "—"}` : "In progress"}</p>
        </div>
        {snapshot.exam?.questions?.map((question, index) => {
          const result = snapshot.exam?.results?.find((attempt) => attempt.exercise_id === question.id)
          return <article key={question.id} className="rounded-2xl border border-border/60 bg-card/40 p-5 sm:p-6">
            <p className="mb-3 text-xs font-medium uppercase tracking-wide text-secondary">Question {index + 1} · {question.concept || question.exercise_type}</p>
            <h2 className="font-medium leading-relaxed">{question.prompt}</h2>
            <p className="mt-4 whitespace-pre-wrap text-sm text-muted-foreground"><span className="font-medium text-foreground">Your answer:</span> {snapshot.exam?.answers?.[question.id] || "No answer saved"}</p>
            {result && <div className="mt-4 space-y-2 rounded-xl bg-muted/40 p-4 text-sm">
              {result.score != null && <p className="font-medium">Score: {result.score}/{result.max_score ?? "—"}</p>}
              <p className="whitespace-pre-wrap text-muted-foreground">{result.feedback}</p>
              {result.expected_answer && <p className="whitespace-pre-wrap"><span className="font-medium">Expected answer:</span> {result.expected_answer}</p>}
            </div>}
          </article>
        })}
      </section>}

      {!snapshot && <section className="space-y-5 rounded-2xl border border-border/60 bg-card/40 p-5 sm:p-7">
        {item.content.explanation ? <>
          {item.content.explanation.definition && <p className="font-medium">{item.content.explanation.definition}</p>}
          {item.content.explanation.intuition && <p className="whitespace-pre-wrap leading-relaxed text-muted-foreground">{item.content.explanation.intuition}</p>}
          {item.content.explanation.sections?.map((section, index) => <div key={index} className="space-y-2 border-t border-border/50 pt-4">
            <h2 className="font-medium">{section.heading}</h2>
            {section.content && <p className="whitespace-pre-wrap leading-relaxed text-muted-foreground">{section.content}</p>}
            {section.code && <pre className="overflow-x-auto rounded-lg bg-muted/60 p-4 text-xs"><code>{section.code}</code></pre>}
          </div>)}
          {item.content.explanation.course_example && <p className="whitespace-pre-wrap text-muted-foreground">{item.content.explanation.course_example}</p>}
        </> : <>
          <p className="whitespace-pre-wrap leading-relaxed">{item.content.solution?.expected_answer || item.content.expected_answer || ""}</p>
          {item.content.correction?.overall_feedback && <p className="whitespace-pre-wrap text-muted-foreground">{item.content.correction.overall_feedback}</p>}
          {item.content.solution?.common_mistakes?.length ? <ul className="list-disc space-y-1 pl-5 text-muted-foreground">{item.content.solution.common_mistakes.map((mistake, index) => <li key={index}>{mistake}</li>)}</ul> : null}
        </>}
      </section>}
    </> : null}
  </main>
}
