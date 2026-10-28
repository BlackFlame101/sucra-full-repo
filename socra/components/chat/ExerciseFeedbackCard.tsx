"use client"

import { ArrowRight, CheckCircle2, Eye, Lightbulb, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { PublicCorrection, PublicSolution } from "@/lib/socra-ws"

export function ExerciseFeedbackCard({
  correction,
  solution,
  onRevealSolution,
  onNextExercise,
  disabled = false,
}: {
  correction: PublicCorrection
  solution: PublicSolution | null
  onRevealSolution: () => void
  onNextExercise: () => void
  disabled?: boolean
}) {
  return (
    <section className="mx-4 mb-4 space-y-4 rounded-2xl border border-secondary/25 bg-card p-5 shadow-sm sm:mx-6 sm:p-6" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-5 w-5 text-secondary" />
          <h3 className="text-lg font-semibold text-foreground">Your feedback</h3>
        </div>
        <div className="rounded-full bg-secondary/10 px-4 py-2 text-base font-semibold text-foreground">
          {correction.total_score} / {correction.max_score}
        </div>
      </div>

      <p className="text-sm leading-relaxed text-foreground">{correction.overall_feedback}</p>

      <div className="space-y-3">
        <h4 className="text-sm font-semibold text-foreground">Rubric breakdown</h4>
        <ul className="space-y-3">
          {correction.criterion_feedback.map((item) => (
            <li key={item.criterion} className="rounded-xl bg-muted/40 p-4">
              <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
                <p className="text-sm font-medium text-foreground">{item.criterion}</p>
                <span className="shrink-0 text-sm font-semibold text-foreground">
                  {item.awarded_points} / {item.possible_points}
                </span>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{item.feedback}</p>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-xl border border-primary/15 bg-primary/5 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Lightbulb className="h-4 w-4 text-primary" /> Next step
        </div>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{correction.next_step}</p>
      </div>

      {correction.citations.length > 0 && (
        <details className="rounded-xl border border-border/70 px-4 py-3">
          <summary className="cursor-pointer text-sm font-medium text-foreground">Review the course pages used</summary>
          <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
            {correction.citations.map((citation, index) => (
              <li key={`${citation.document_id}-${citation.page_number}-${index}`}>
                {citation.filename}, page {citation.page_number}
              </li>
            ))}
          </ul>
        </details>
      )}

      {solution ? (
        <div className="space-y-3 rounded-xl border border-primary/20 bg-primary/5 p-4">
          <h4 className="text-sm font-semibold text-foreground">Suggested answer</h4>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{solution.expected_answer}</p>
          {solution.common_mistakes.length > 0 && (
            <div>
              <p className="text-sm font-medium text-foreground">Common pitfalls</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {solution.common_mistakes.map((mistake, index) => <li key={index}>{mistake}</li>)}
              </ul>
            </div>
          )}
          <p className="text-xs text-muted-foreground">You have revealed the solution for this exercise.</p>
        </div>
      ) : (
        <Button type="button" variant="outline" className="gap-2" onClick={onRevealSolution} disabled={disabled}>
          <Eye className="h-4 w-4" /> Reveal suggested answer
        </Button>
      )}

      <div className="flex justify-end border-t border-border/70 pt-4">
        <Button type="button" className="gap-2" onClick={onNextExercise} disabled={disabled}>
          <Sparkles className="h-4 w-4" /> Generate another question <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </section>
  )
}
