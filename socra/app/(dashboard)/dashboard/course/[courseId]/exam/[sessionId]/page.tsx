"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useParams, useSearchParams } from "next/navigation"
import { ArrowLeft, ArrowRight, BookOpen, Bookmark, CheckCircle2, ClipboardCheck, LoaderCircle, SkipForward } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useUserSettings } from "@/hooks/useUserSettings"
import type { CourseExam, ExamQuestion } from "@/lib/exams"
import { toast } from "sonner"

const EXAM_QUESTION_TYPES = [
  { id: "short_answer", label: "Short answer", help: "Explain or recall concepts" },
  { id: "multiple_choice", label: "Multiple choice", help: "Choose the supported option" },
  { id: "numerical", label: "Numerical", help: "Solve a course-based calculation" },
  { id: "code", label: "Code completion", help: "Fill in one or more missing words or expressions from your course" },
  { id: "sql", label: "SQL query", help: "Write a read-only SQLite query" },
] as const
const DEFAULT_EXAM_TYPES = ["short_answer", "multiple_choice", "numerical"]
type ExamDifficulty = "beginner" | "intermediate" | "advanced"

function errorDetail(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail
  }
  return fallback
}

function answerForInput(question: ExamQuestion, stored: string) {
  if (question.exercise_type !== "numerical" || !question.numeric_unit) return stored
  const escaped = question.numeric_unit.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  return stored.replace(new RegExp(`\\s+${escaped}$`, "i"), "")
}

function completionBlankCount(question: ExamQuestion) {
  return question.exercise_type === "code" && question.code_task_mode === "completion"
    ? question.starter_code.match(/____/g)?.length ?? 0
    : 0
}

function completionAnswersFor(question: ExamQuestion, answer: string) {
  const count = completionBlankCount(question)
  if (count === 0) return []
  if (!answer.trim()) return Array.from({ length: count }, () => "")
  try {
    const decoded: unknown = JSON.parse(answer)
    if (Array.isArray(decoded)) return Array.from({ length: count }, (_, index) => String(decoded[index] ?? ""))
  } catch {
    // Preserve answers saved by the earlier single-blank format.
  }
  return count === 1 ? [answer] : Array.from({ length: count }, () => "")
}

function hasAnswerForQuestion(question: ExamQuestion, answer: string) {
  const count = completionBlankCount(question)
  if (count > 0) {
    const values = completionAnswersFor(question, answer)
    return values.length === count && values.every((value) => value.trim().length > 0)
  }
  return Boolean(answer?.trim())
}

function displaySubmittedAnswer(exerciseType: ExamQuestion["exercise_type"], codeTaskMode: ExamQuestion["code_task_mode"], answer: string) {
  if (exerciseType === "code" && codeTaskMode === "completion") {
    try {
      const values: unknown = JSON.parse(answer)
      if (Array.isArray(values)) return values.map((value, index) => `Blank ${index + 1}: ${String(value)}`).join(" · ")
    } catch {
      // Older saved single-blank answers were plain text.
    }
  }
  return answer
}

export default function MixedExamPage() {
  const { courseId, sessionId } = useParams<{ courseId: string; sessionId: string }>()
  const searchParams = useSearchParams()
  const restoreSavedExam = searchParams.get("restore") === "1"
  const { getActiveConfig, loaded: settingsLoaded } = useUserSettings()
  const activeConfig = getActiveConfig()
  const examStorageKey = `socra:exam:${sessionId}`

  const [exam, setExam] = useState<CourseExam | null>(null)
  const [topic, setTopic] = useState("")
  const [questionCount, setQuestionCount] = useState(6)
  const [selectedTypes, setSelectedTypes] = useState<string[]>(DEFAULT_EXAM_TYPES)
  const [difficulty, setDifficulty] = useState<ExamDifficulty>("beginner")
  const [currentIndex, setCurrentIndex] = useState(0)
  const [answer, setAnswer] = useState("")
  const [initializing, setInitializing] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [sessionSavedToLibrary, setSessionSavedToLibrary] = useState(false)
  const [savingSessionToLibrary, setSavingSessionToLibrary] = useState(false)
  const [language, setLanguage] = useState<"fr" | "en">("fr")

  const questions = exam?.questions ?? []
  const currentQuestion = questions[currentIndex]
  const isCodeCompletion = currentQuestion?.exercise_type === "code" && currentQuestion.code_task_mode === "completion"
  const completedResults = useMemo(() => exam?.results ?? [], [exam?.results])
  const missingQuestionTypes = useMemo(() => {
    if (!exam) return []
    const available = new Set(exam.questions.map((question) => question.exercise_type))
    return ([
      ["short_answer", "short-answer"],
      ["multiple_choice", "QCM"],
      ["numerical", "numerical"],
      ["code", "Code completion"],
      ["sql", "SQL query"],
    ] as const).filter(([type]) => exam.requested_types.includes(type) && !available.has(type)).map(([, label]) => label)
  }, [exam])

  useEffect(() => {
    let cancelled = false
    setSessionSavedToLibrary(false)
    fetch(`/api/library/sessions/${encodeURIComponent(sessionId)}`)
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => { if (!cancelled) setSessionSavedToLibrary(payload?.saved === true && payload?.item_type === "exam") })
      .catch(() => {})
    return () => { cancelled = true }
  }, [sessionId])

  useEffect(() => {
    let cancelled = false
    setInitializing(true)
    setExam(null)
    setError("")
    const storedId = window.localStorage.getItem(examStorageKey)
    fetch(`/api/sessions/${courseId}`).then((response) => response.ok ? response.json() : []).then((sessions) => {
      const current = sessions.find((session: { id: string; language?: string }) => session.id === sessionId)
      if (current?.language === "fr" || current?.language === "en") setLanguage(current.language)
    }).catch(() => {})
    if (!storedId && !restoreSavedExam) {
      setInitializing(false)
      return () => { cancelled = true }
    }
    const examUrl = storedId
      ? `/api/exams/${encodeURIComponent(storedId)}`
      : `/api/exams/session/${encodeURIComponent(sessionId)}`

    fetch(examUrl, { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json()
        if (!response.ok) throw new Error(errorDetail(payload, "Could not restore this exam."))
        return payload as CourseExam
      })
      .then((restored) => {
        if (cancelled) return
        window.localStorage.setItem(examStorageKey, restored.id)
        setExam(restored)
        setTopic(restored.topic)
        setQuestionCount(restored.questions.length)
        const unanswered = restored.questions.findIndex((question) => !hasAnswerForQuestion(question, restored.answers[question.id] ?? ""))
        setCurrentIndex(unanswered >= 0 ? unanswered : Math.max(0, restored.questions.length - 1))
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          if (storedId) window.localStorage.removeItem(examStorageKey)
          setError(cause instanceof Error ? cause.message : "Could not restore this exam.")
        }
      })
      .finally(() => { if (!cancelled) setInitializing(false) })
    return () => { cancelled = true }
  }, [examStorageKey, restoreSavedExam, sessionId, courseId])

  useEffect(() => {
    if (!currentQuestion || !exam) {
      setAnswer("")
      return
    }
    setAnswer(answerForInput(currentQuestion, exam.answers[currentQuestion.id] ?? ""))
  }, [currentQuestion, exam])

  const modelOptions = () => {
    const provider = activeConfig.provider === "xai" ? "xai" : "google"
    const supportsProvider = activeConfig.provider === "google" || activeConfig.provider === "xai"
    return {
      provider,
      api_key: supportsProvider ? activeConfig.apiKey ?? "" : "",
      model: supportsProvider ? activeConfig.model ?? "" : "",
    }
  }

  const saveLanguage = async (nextLanguage: "fr" | "en") => {
    const response = await fetch(`/api/sessions/update/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: nextLanguage }),
    })
    if (!response.ok) throw new Error("Could not save the response language.")
  }

  const startExam = async () => {
    setBusy(true)
    setError("")
    try {
      await saveLanguage(language)
      const response = await fetch("/api/exams/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_id: courseId,
          session_id: sessionId,
          topic: topic.trim(),
          question_count: questionCount,
          exercise_types: selectedTypes,
          difficulty,
          language,
          ...modelOptions(),
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(errorDetail(payload, "Could not build a verified exam."))
      const started = payload as CourseExam
      window.localStorage.setItem(examStorageKey, started.id)
      setExam(started)
      setCurrentIndex(0)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not build a verified exam.")
    } finally {
      setBusy(false)
    }
  }

  const saveAnswer = async () => {
    if (!exam || !currentQuestion || !answer.trim()) return
    const submitted = currentQuestion.exercise_type === "numerical" && currentQuestion.numeric_unit
      ? `${answer.trim()} ${currentQuestion.numeric_unit}`
      : answer.trim()
    const response = await fetch(`/api/exams/${encodeURIComponent(exam.id)}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exercise_id: currentQuestion.id, answer: submitted }),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(errorDetail(payload, "Could not save your answer."))
    setExam((previous) => previous ? {
      ...previous,
      answers: { ...previous.answers, [currentQuestion.id]: submitted },
    } : previous)
  }

  const saveExamToLibrary = async () => {
    if (!exam) return
    setSavingSessionToLibrary(true)
    try {
      if (exam.status === "in_progress" && answer.trim()) await saveAnswer()
      const response = await fetch(`/api/library/sessions/${encodeURIComponent(sessionId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_type: "exam" }),
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(payload?.error || "Could not save this exam to your Library.")
      setSessionSavedToLibrary(true)
      toast.success("Saved to Library", { description: "This exam snapshot is ready to revisit." })
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not save this exam to your Library.")
    } finally {
      setSavingSessionToLibrary(false)
    }
  }

  const submitExam = async () => {
    if (!exam) return
    await saveLanguage(language)
    const response = await fetch(`/api/exams/${encodeURIComponent(exam.id)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(modelOptions()),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(errorDetail(payload, "Could not grade the exam."))
    setExam(payload as CourseExam)
  }

  const continueExam = async () => {
    if (!exam || !currentQuestion) return
    setBusy(true)
    setError("")
    try {
      await saveAnswer()
      if (currentIndex < questions.length - 1) {
        setCurrentIndex((index) => index + 1)
      } else {
        const unanswered = questions.findIndex((question) => {
          const isCurrentQuestion = question.id === currentQuestion.id
          return !hasAnswerForQuestion(question, isCurrentQuestion ? answer : exam.answers[question.id] ?? "")
        })
        if (unanswered >= 0) {
          setCurrentIndex(unanswered)
          setError("Answer every question before submitting, or use the question list to review unanswered items.")
          return
        }
        await submitExam()
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your answer.")
    } finally {
      setBusy(false)
    }
  }

  const goToQuestion = async (index: number) => {
    if (!exam || index === currentIndex) return
    setBusy(true)
    setError("")
    try {
      await saveAnswer()
      setCurrentIndex(index)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your answer.")
    } finally {
      setBusy(false)
    }
  }

  const previousQuestion = async () => {
    if (!exam || currentIndex === 0) return
    setBusy(true)
    setError("")
    try {
      if (answer.trim()) await saveAnswer()
      setCurrentIndex((index) => index - 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your answer.")
    } finally {
      setBusy(false)
    }
  }

  const questionTypeLabel = (
    type: ExamQuestion["exercise_type"],
    codeTaskMode?: ExamQuestion["code_task_mode"],
  ) => {
    if (type === "code" && codeTaskMode === "write") return "Python code"
    return ({
      short_answer: "Short answer",
      multiple_choice: "QCM",
      numerical: "Numerical",
      code: "Code completion",
      sql: "SQL query",
    })[type]
  }

  const resultTypeLabel = (type: ExamQuestion["exercise_type"], codeTaskMode?: ExamQuestion["code_task_mode"]) =>
    questionTypeLabel(type, codeTaskMode)

  return (
    <main className="container mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-12">
      <Link
        href={`/dashboard/course/${courseId}`}
        className="mb-8 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Back to course
      </Link>

      <div className="mb-8">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-secondary/30 bg-secondary/10 px-3 py-1 text-xs font-medium uppercase tracking-wider text-secondary">
          <ClipboardCheck className="h-3.5 w-3.5" /> Mixed course exam
        </div>
        <Button type="button" variant="outline" size="sm" className="gap-1.5" disabled={!exam || busy || savingSessionToLibrary || sessionSavedToLibrary} onClick={() => void saveExamToLibrary()}>
          <Bookmark className={`h-4 w-4 ${sessionSavedToLibrary ? "fill-current text-secondary" : ""}`} />
          {savingSessionToLibrary ? "Saving…" : sessionSavedToLibrary ? "Saved to Library" : "Save to Library"}
        </Button>
      </div>
        <h1 className="font-serif text-3xl font-medium tracking-tight sm:text-4xl">
          {exam?.status === "completed" ? "Exam results" : "Test your course knowledge"}
        </h1>
        <p className="mt-3 max-w-2xl leading-relaxed text-muted-foreground">
          {exam ? `${exam.questions.length} verified, course-grounded questions. Your answers are graded together when you finish.` : "Choose your question types and exam length. Socra balances selected types as evenly as possible and uses only formats the course material can support."}
        </p>
      </div>

      <div className="mb-6 max-w-xs space-y-2">
        <label htmlFor="exam-language" className="text-sm font-medium">Response language</label>
        <Select value={language} onValueChange={async (value) => {
          const nextLanguage = value as "fr" | "en"
          try {
            await saveLanguage(nextLanguage)
            setLanguage(nextLanguage)
            setError("")
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : "Could not save the response language.")
          }
        }}>
          <SelectTrigger id="exam-language" aria-label="Response language"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="fr">Français</SelectItem><SelectItem value="en">English</SelectItem></SelectContent>
        </Select>
      </div>

      {error && <div role="alert" className="mb-6 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>}
      {exam && missingQuestionTypes.length > 0 && (
        <div role="status" className="mb-6 rounded-xl border border-secondary/30 bg-secondary/5 p-4 text-sm text-muted-foreground">
          This course material could not support {missingQuestionTypes.join(", ")} questions, so Socra filled the exam with other verified formats.
        </div>
      )}

      {initializing ? (
        <div className="flex items-center gap-3 rounded-2xl border border-border/60 bg-card/40 p-6 text-muted-foreground">
          <LoaderCircle className="h-5 w-5 animate-spin" /> Restoring your exam…
        </div>
      ) : !exam ? (
        <section className="rounded-2xl border border-border/60 bg-card/40 p-5 sm:p-7">
          <h2 className="text-lg font-medium">Choose a focus (optional)</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Leave this blank to draw questions from across the course, or name a topic such as internships or personal projects.
          </p>
          <Input
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="All course topics"
            maxLength={300}
            className="mt-5 h-11"
            disabled={busy}
          />
          <fieldset className="mt-6 space-y-3" disabled={busy}>
            <legend className="text-sm font-medium">Question types</legend>
            <p className="text-xs text-muted-foreground">Choose one or more. Each selected type appears at least once, so the shortest exam matches the number of selected types. Unavailable types may be replaced by another selected type.</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {EXAM_QUESTION_TYPES.map((type) => {
                const checked = selectedTypes.includes(type.id)
                const atLimit = !checked && selectedTypes.length >= questionCount
                return (
                  <label key={type.id} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${checked ? "border-primary/50 bg-primary/5" : "border-border/70 hover:bg-muted/30"} ${atLimit ? "cursor-not-allowed opacity-50" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={atLimit || (checked && selectedTypes.length === 1)}
                      onChange={() => setSelectedTypes((current) => {
                        const next = current.includes(type.id)
                          ? current.filter((item) => item !== type.id)
                          : [...current, type.id]
                        return next
                      })}
                      className="mt-1 accent-primary"
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{type.label}</span>
                      <span className="block text-xs text-muted-foreground">{type.help}</span>
                    </span>
                  </label>
                )
              })}
            </div>
          </fieldset>
          <div className="mt-5 max-w-xs space-y-2">
            <label htmlFor="exam-question-count" className="text-sm font-medium">Number of questions</label>
            <Select value={String(questionCount)} onValueChange={(value) => setQuestionCount(Number(value))} disabled={busy}>
              <SelectTrigger id="exam-question-count" className="h-11" aria-label="Number of exam questions">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Array.from({ length: 10 }, (_, index) => index + 3).filter((count) => count >= selectedTypes.length).map((count) => (
                  <SelectItem key={count} value={String(count)}>{count} questions</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">Choose 3–12 questions. Every selected type appears at least once, then Socra distributes the remaining questions as evenly as possible.</p>
          </div>
          <div className="mt-5 max-w-xs space-y-2">
            <label htmlFor="exam-difficulty" className="text-sm font-medium">Question difficulty</label>
            <Select value={difficulty} onValueChange={(value) => setDifficulty(value as ExamDifficulty)} disabled={busy}>
              <SelectTrigger id="exam-difficulty" className="h-11" aria-label="Question difficulty">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="beginner">Beginner · direct and focused</SelectItem>
                <SelectItem value="intermediate">Intermediate · apply a few steps</SelectItem>
                <SelectItem value="advanced">Advanced · combine ideas</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="mt-5 flex flex-col gap-3 rounded-xl bg-muted/40 p-4 text-sm text-muted-foreground sm:flex-row sm:items-start">
            <BookOpen className="mt-0.5 h-4 w-4 shrink-0" />
            <p>Larger exams can take longer to prepare because Socra verifies each question separately. You’ll see explanations and citations after submitting all your answers. Hints and solutions stay hidden during the exam.</p>
          </div>
          <Button className="mt-6 gap-2" onClick={startExam} disabled={busy || !settingsLoaded || selectedTypes.length === 0 || selectedTypes.length > questionCount}>
            {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}
            {busy ? "Building and verifying your exam…" : "Create my exam"}
          </Button>
        </section>
      ) : exam.status === "completed" ? (
        <section className="space-y-5">
          <div className="flex flex-col gap-2 rounded-2xl border border-secondary/25 bg-secondary/5 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-7">
            <div>
              <p className="text-sm text-muted-foreground">Final score</p>
              <p className="font-serif text-4xl font-medium">{exam.score ?? 0} <span className="text-2xl text-muted-foreground">/ {exam.max_score}</span></p>
            </div>
            <CheckCircle2 className="h-8 w-8 text-secondary" />
          </div>
          {completedResults.map((result, index) => (
            <article key={result.exercise_id} className="rounded-2xl border border-border/60 bg-card/40 p-5 sm:p-6">
              <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded-full bg-primary/10 px-3 py-1 font-medium text-primary">Question {index + 1} · {resultTypeLabel(result.exercise_type, result.code_task_mode)}</span>
                <span className="rounded-full bg-muted px-3 py-1 capitalize text-muted-foreground">{result.concept}</span>
                <span className="ml-auto font-semibold text-foreground">{result.score}/{result.max_score}</span>
              </div>
              <h2 className="text-lg font-medium leading-relaxed">{result.prompt}</h2>
              <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground"><strong className="text-foreground">Your answer:</strong> {displaySubmittedAnswer(result.exercise_type, result.code_task_mode, result.answer)}</p>
              <div className="mt-4 rounded-xl bg-muted/40 p-4 text-sm leading-relaxed">
                <p className="font-medium">Feedback</p>
                <p className="mt-1 text-muted-foreground">{result.feedback}</p>
              </div>
              {result.expected_answer && (
                <div className="mt-4 rounded-xl border border-secondary/25 bg-secondary/5 p-4">
                {result.exercise_type === "code" && result.code_task_mode === "completion" && result.code_expected_answers?.length ? (
                  <>
                    <p className="text-sm font-medium">Expected completions</p>
                    <ol className="mt-2 list-decimal space-y-1 pl-5 font-mono text-xs text-muted-foreground">
                      {result.code_expected_answers.map((value, answerIndex) => <li key={`${result.exercise_id}-expected-${answerIndex}`}>{value}</li>)}
                    </ol>
                  </>
                ) : (
                  <>
                    <p className="text-sm font-medium">Expected answer</p>
                    <pre className={`mt-2 whitespace-pre-wrap break-words text-muted-foreground ${result.exercise_type === "code" || result.exercise_type === "sql" ? "font-mono text-xs" : "font-sans text-sm"}`}>{result.expected_answer}</pre>
                  </>
                )}
                  {result.exercise_type === "code" && result.code_task_mode === "completion" && result.completed_code && (
                    <>
                      <p className="mt-4 text-sm font-medium">Completed code · {result.code_language}</p>
                      <pre className="mt-2 overflow-x-auto rounded-lg bg-muted/60 p-3 font-mono text-xs text-muted-foreground">{result.completed_code}</pre>
                    </>
                  )}
                </div>
              )}
              <ul className="mt-4 space-y-3">
                {result.criterion_feedback.map((criterion) => (
                  <li key={criterion.criterion} className="border-l-2 border-secondary/40 pl-3 text-sm">
                    <div className="flex justify-between gap-3"><span className="font-medium">{criterion.criterion}</span><span className="shrink-0 text-muted-foreground">{criterion.awarded_points}/{criterion.possible_points}</span></div>
                    <p className="mt-1 text-muted-foreground">{criterion.feedback}</p>
                  </li>
                ))}
              </ul>
              {result.citations.length > 0 && <p className="mt-4 text-xs text-muted-foreground">Course pages: {result.citations.map((citation) => `${citation.filename} · page ${citation.page_number}`).join("; ")}</p>}
              <p className="mt-3 text-sm text-secondary">{result.next_step}</p>
            </article>
          ))}
        </section>
      ) : currentQuestion ? (
        <section className="rounded-2xl border border-border/60 bg-card/40 p-5 sm:p-7">
          <div className="mb-6 flex flex-wrap gap-2" aria-label="Exam questions">
            {questions.map((question, index) => {
              const hasAnswer = question.id === currentQuestion.id
                ? hasAnswerForQuestion(question, answer)
                : hasAnswerForQuestion(question, exam.answers[question.id] ?? "")
              return (
                <Button
                  key={question.id}
                  type="button"
                  variant={index === currentIndex ? "default" : "outline"}
                  size="sm"
                  onClick={() => void goToQuestion(index)}
                  disabled={busy}
                  aria-current={index === currentIndex ? "step" : undefined}
                  aria-label={`Question ${index + 1}${hasAnswer ? ", answered" : ", unanswered"}`}
                  className="gap-1.5"
                >
                  {index + 1}
                  {hasAnswer && <CheckCircle2 className="h-3.5 w-3.5" />}
                </Button>
              )
            })}
          </div>
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-medium">Question {currentIndex + 1} <span className="text-muted-foreground">of {questions.length}</span></p>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">{questionTypeLabel(currentQuestion.exercise_type, currentQuestion.code_task_mode)}</span>
              <span className="rounded-full bg-muted px-3 py-1 text-xs capitalize text-muted-foreground">{currentQuestion.difficulty}</span>
            </div>
          </div>
          <div className="mb-6 h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-secondary transition-all" style={{ width: `${((currentIndex + 1) / questions.length) * 100}%` }} />
          </div>

          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{currentQuestion.concept}</p>
          <h2 className="mt-2 text-xl font-medium leading-relaxed sm:text-2xl">{currentQuestion.prompt}</h2>

          <div className="mt-7 space-y-3">
            <p className="text-sm font-medium">Your answer</p>
            {currentQuestion.exercise_type === "sql" && currentQuestion.sql_setup.length > 0 && (
              <details className="mb-4 rounded-xl border border-border/60 p-3">
                <summary className="cursor-pointer text-sm font-medium">View the practice tables and sample rows</summary>
                <pre className="mt-3 overflow-x-auto rounded-lg bg-muted/60 p-3 text-xs"><code>{currentQuestion.sql_setup.join("\n")}</code></pre>
              </details>
            )}
            {currentQuestion.exercise_type === "code" && currentQuestion.starter_code && (
              <div className="mb-4">
                <p className="mb-1 text-xs text-muted-foreground">{isCodeCompletion ? "Fill in the missing parts" : "Starter code"} · {currentQuestion.code_language}</p>
                <pre className="overflow-x-auto rounded-lg bg-muted/60 p-3 text-xs"><code>{currentQuestion.starter_code}</code></pre>
              </div>
            )}
            {currentQuestion.exercise_type === "multiple_choice" ? (
              <fieldset className="space-y-2" disabled={busy}>
                <legend className="sr-only">Choose one answer</legend>
                {currentQuestion.choices.map((choice) => (
                  <label key={choice.id} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 text-sm transition-colors ${answer === choice.id ? "border-primary bg-primary/5" : "border-border/70 hover:bg-muted/40"}`}>
                    <input type="radio" name={`exam-${currentQuestion.id}`} value={choice.id} checked={answer === choice.id} onChange={() => setAnswer(choice.id)} className="mt-0.5 accent-primary" />
                    <span><strong className="mr-2">{choice.id}.</strong>{choice.text}</span>
                  </label>
                ))}
              </fieldset>
            ) : currentQuestion.exercise_type === "numerical" ? (
              <div className="flex items-center gap-3">
                <Input type="text" inputMode="decimal" value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="Enter a value" disabled={busy} className="h-11" />
                {currentQuestion.numeric_unit && <span className="shrink-0 text-sm text-muted-foreground">{currentQuestion.numeric_unit}</span>}
              </div>
            ) : isCodeCompletion ? (
              <div className="space-y-2">
                {completionAnswersFor(currentQuestion, answer).map((value, index) => (
                  <label key={`${currentQuestion.id}-blank-${index}`} className="flex items-center gap-3">
                    <span className="shrink-0 text-xs font-medium text-muted-foreground">Blank {index + 1}</span>
                    <Input
                      value={value}
                      onChange={(event) => {
                        const updated = completionAnswersFor(currentQuestion, answer).map((item, itemIndex) => itemIndex === index ? event.target.value : item)
                        setAnswer(updated.some((item) => item.trim()) ? JSON.stringify(updated) : "")
                      }}
                      placeholder="Type the missing word or expression…"
                      maxLength={200}
                      disabled={busy}
                      spellCheck={false}
                      className="h-11 font-mono"
                    />
                  </label>
                ))}
              </div>
            ) : (
              <Textarea value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder={currentQuestion.exercise_type === "sql" ? "Write a SELECT query…" : currentQuestion.exercise_type === "code" ? "Write your Python solution…" : "Write your answer in your own words…"} rows={currentQuestion.exercise_type === "code" || currentQuestion.exercise_type === "sql" ? 12 : 5} maxLength={10000} disabled={busy} spellCheck={currentQuestion.exercise_type !== "code" && currentQuestion.exercise_type !== "sql"} className={currentQuestion.exercise_type === "code" || currentQuestion.exercise_type === "sql" ? "font-mono" : undefined} />
            )}
          </div>

          <div className="mt-7 flex flex-col-reverse gap-3 border-t border-border/50 pt-5 sm:flex-row sm:items-center sm:justify-between">
            <Button variant="outline" onClick={previousQuestion} disabled={busy || currentIndex === 0}>Previous</Button>
            <p className="text-center text-xs text-muted-foreground">You can skip questions and return later. Answers save when you navigate. No hints or feedback until you finish.</p>
            <Button onClick={continueExam} disabled={busy} className="gap-2">
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
              {busy ? "Saving…" : currentIndex === questions.length - 1 ? "Submit exam" : answer.trim() ? "Save and continue" : "Skip question"}
              {!busy && !answer.trim() && currentIndex < questions.length - 1 && <SkipForward className="h-4 w-4" />}
              {!busy && <ArrowRight className="h-4 w-4" />}
            </Button>
          </div>
        </section>
      ) : (
        <section className="rounded-2xl border border-border/60 bg-card/40 p-6 text-sm text-muted-foreground">This exam has no available questions. Return to the course and create another exam.</section>
      )}
    </main>
  )
}
