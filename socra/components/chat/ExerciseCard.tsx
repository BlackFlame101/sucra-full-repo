"use client"

import { useEffect, useState } from "react"
import { ArrowRight, BookOpen, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { PublicExercise } from "@/lib/socra-ws"

export function ExerciseCard({
  exercise,
  onNextExercise,
  onSubmitAttempt,
  disabled = false,
  submissionLocked = false,
}: {
  exercise: PublicExercise
  onNextExercise: () => void
  onSubmitAttempt: (answer: string, hintsUsed: number) => void
  disabled?: boolean
  submissionLocked?: boolean
}) {
  const [revealedHints, setRevealedHints] = useState(0)
  const [answer, setAnswer] = useState("")
  const isCodeCompletion = exercise.exercise_type === "code" && exercise.code_task_mode === "completion"
  const codeBlankCount = isCodeCompletion ? exercise.starter_code.match(/____/g)?.length ?? 0 : 0
  const [completionAnswers, setCompletionAnswers] = useState<string[]>([])

  useEffect(() => {
    setAnswer("")
    setRevealedHints(0)
    setCompletionAnswers(Array.from({ length: codeBlankCount }, () => ""))
  }, [exercise.id, codeBlankCount])

  const revealNextHint = () => {
    const nextCount = Math.min(revealedHints + 1, exercise.hints.length)
    setRevealedHints(nextCount)
  }

  const submitAnswer = () => {
    if (disabled || submissionLocked) return
    if (isCodeCompletion) {
      if (completionAnswers.length !== codeBlankCount || completionAnswers.some((value) => !value.trim())) return
      onSubmitAttempt(JSON.stringify(completionAnswers.map((value) => value.trim())), revealedHints)
      return
    }
    if (!answer.trim()) return
    const trimmedAnswer = answer.trim()
    const submittedAnswer = exercise.exercise_type === "numerical" && exercise.numeric_unit &&
      !trimmedAnswer.toLocaleLowerCase().endsWith(exercise.numeric_unit.toLocaleLowerCase())
      ? `${trimmedAnswer} ${exercise.numeric_unit}`
      : trimmedAnswer
    onSubmitAttempt(submittedAnswer, revealedHints)
  }

  return (
    <section className="mx-4 mb-4 rounded-2xl border border-primary/20 bg-card shadow-sm sm:mx-6">
      <div className="space-y-5 p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
            <BookOpen className="h-3.5 w-3.5" /> {{
              multiple_choice: "Multiple choice",
              numerical: "Numerical",
              code: isCodeCompletion ? "Code completion" : "Python coding",
              sql: "SQL query",
              short_answer: "Short answer",
            }[exercise.exercise_type]}
          </span>
          <span className="rounded-full bg-muted px-3 py-1 text-xs capitalize text-muted-foreground">
            {exercise.difficulty}
          </span>
          <span className="rounded-full bg-muted px-3 py-1 text-xs capitalize text-muted-foreground">
            {exercise.bloom_level}
          </span>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Your question</p>
          <h3 className="text-lg font-medium leading-relaxed text-foreground sm:text-xl">
            {exercise.prompt}
          </h3>
          <p className="text-sm text-muted-foreground">Topic: {exercise.concept}</p>
        </div>

        <div className="space-y-3 rounded-xl border border-border/70 p-4">
          <p className="text-sm font-medium text-foreground">Your answer</p>
          {exercise.exercise_type === "multiple_choice" ? (
            <fieldset className="space-y-2" disabled={submissionLocked}>
              <legend className="sr-only">Choose one answer</legend>
              {exercise.choices.map((choice) => (
                <label key={choice.id} className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition-colors ${answer === choice.id ? "border-primary bg-primary/5" : "border-border/70 hover:bg-muted/40"}`}>
                  <input type="radio" name={`exercise-choice-${exercise.id}`} value={choice.id} checked={answer === choice.id} onChange={() => setAnswer(choice.id)} className="mt-0.5 accent-primary" />
                  <span><strong className="mr-2">{choice.id}.</strong>{choice.text}</span>
                </label>
              ))}
            </fieldset>
          ) : exercise.exercise_type === "numerical" ? (
            <div className="flex items-center gap-2">
              <input
                id="exercise-answer"
                type="text"
                inputMode="decimal"
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitAnswer() }}
                placeholder={exercise.numeric_unit ? `Enter a value in ${exercise.numeric_unit}` : "Enter a number"}
                disabled={disabled || submissionLocked}
                maxLength={100}
                className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
              />
              {exercise.numeric_unit && <span className="shrink-0 text-sm text-muted-foreground">{exercise.numeric_unit}</span>}
            </div>
          ) : isCodeCompletion ? (
            <div className="space-y-3">
              <div>
                <p className="mb-1 text-xs text-muted-foreground">Fill in the missing parts · {exercise.code_language}</p>
                <pre className="overflow-x-auto rounded-lg bg-muted/60 p-3 text-xs"><code>{exercise.starter_code}</code></pre>
              </div>
              <div className="space-y-2">
                {completionAnswers.map((value, index) => (
                  <label key={`${exercise.id}-blank-${index}`} className="flex items-center gap-3">
                    <span className="shrink-0 text-xs font-medium text-muted-foreground">Blank {index + 1}</span>
                    <input
                      type="text"
                      value={value}
                      onChange={(event) => setCompletionAnswers((previous) => previous.map((item, itemIndex) => itemIndex === index ? event.target.value : item))}
                      onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitAnswer() }}
                      placeholder="Type the missing word or expression…"
                      disabled={disabled || submissionLocked}
                      maxLength={200}
                      spellCheck={false}
                      className="w-full rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm text-foreground placeholder:font-sans placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                    />
                  </label>
                ))}
              </div>
            </div>
          ) : exercise.exercise_type === "code" || exercise.exercise_type === "sql" ? (
            <div className="space-y-3">
              {exercise.exercise_type === "code" && exercise.starter_code && (
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">Starter code · {exercise.code_language}</p>
                  <pre className="overflow-x-auto rounded-lg bg-muted/60 p-3 text-xs"><code>{exercise.starter_code}</code></pre>
                </div>
              )}
              {exercise.exercise_type === "sql" && (
                <details className="rounded-lg border border-border/60 p-3">
                  <summary className="cursor-pointer text-sm font-medium">View the practice tables and sample rows</summary>
                  <pre className="mt-3 overflow-x-auto rounded-lg bg-muted/60 p-3 text-xs"><code>{exercise.sql_setup.join("\n")}</code></pre>
                </details>
              )}
              <textarea
                id="exercise-answer"
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitAnswer() }}
                placeholder={exercise.exercise_type === "sql" ? "Write a SELECT query…" : "Write your Python solution…"}
                disabled={disabled || submissionLocked}
                rows={12}
                maxLength={10000}
                spellCheck={false}
                className="w-full resize-y rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-sm leading-relaxed text-foreground placeholder:font-sans placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>
          ) : (
            <textarea
              id="exercise-answer"
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitAnswer() }}
              placeholder="Write a few sentences in your own words…"
              disabled={disabled || submissionLocked}
              rows={4}
              maxLength={10000}
              className="w-full resize-y rounded-lg border border-input bg-background px-3 py-2.5 text-sm leading-relaxed text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
            />
          )}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muted-foreground">{exercise.exercise_type === "multiple_choice" ? "Choose one answer." : exercise.exercise_type === "numerical" ? "Use a decimal point or comma." : exercise.exercise_type === "sql" ? "Only read-only SQLite queries are accepted." : isCodeCompletion ? "Enter only the missing word or expression; no code is executed." : exercise.exercise_type === "code" ? "Python syntax is checked; your code is reviewed against the course rubric and is not executed." : "Your answer is graded against the course rubric."} Press Ctrl/⌘ + Enter to submit.</p>
            <Button type="button" onClick={submitAnswer} disabled={disabled || submissionLocked || (isCodeCompletion ? completionAnswers.length !== codeBlankCount || completionAnswers.some((value) => !value.trim()) : !answer.trim())}>
              Submit answer
            </Button>
          </div>
        </div>

        {exercise.hints.length > 0 && (
          <div className="space-y-3 rounded-xl bg-muted/40 p-4">
            <div>
              <p className="text-sm font-medium text-foreground">Need a hint?</p>
              <p className="text-xs text-muted-foreground">Hints appear one at a time, from gentle nudge to stronger clue.</p>
            </div>
            {revealedHints > 0 && (
              <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed text-foreground">
                {exercise.hints.slice(0, revealedHints).map((hint, index) => (
                  <li key={`${exercise.id}-hint-${index}`}>{hint}</li>
                ))}
              </ol>
            )}
            {revealedHints < exercise.hints.length && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={revealNextHint}
              >
                Reveal hint {revealedHints + 1}
              </Button>
            )}
          </div>
        )}

        <details className="group rounded-xl border border-border/70 bg-background/40">
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-foreground marker:hidden">
            <span className="inline-flex items-center gap-2">
              <BookOpen className="h-4 w-4 text-muted-foreground" />
              Course sources ({exercise.citations.length})
              <span className="text-xs font-normal text-muted-foreground group-open:hidden">Show excerpts</span>
              <span className="hidden text-xs font-normal text-muted-foreground group-open:inline">Hide excerpts</span>
            </span>
          </summary>
          <div className="space-y-3 border-t border-border/70 px-4 py-3">
            {exercise.citations.map((citation, index) => (
              <details key={`${citation.document_id}-${citation.page_number}-${index}`} className="rounded-lg bg-muted/40 p-3">
                <summary className="cursor-pointer text-sm font-medium text-foreground">
                  {citation.filename} <span className="font-normal text-muted-foreground">· page {citation.page_number}</span>
                </summary>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">“{citation.excerpt}”</p>
              </details>
            ))}
          </div>
        </details>

        <div className="flex flex-col gap-3 border-t border-border/70 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">Your answer is checked against the course material.</p>
          <Button type="button" className="gap-2" onClick={onNextExercise} disabled={disabled}>
            <Sparkles className="h-4 w-4" />
            Generate another question
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </section>
  )
}
