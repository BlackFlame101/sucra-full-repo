"use client"

/**
 * Diagnostic gate — runs the **Diagnostiqueur** + **Tuteur Socratique** agents
 * on the very first turn of a brand new inquiry session, so the student sees
 * the multi-agent system at work before the chat starts.
 *
 * Flow:
 *   1. User picks the topic they want to study (typed or suggested).
 *   2. We open the backend WS and send the topic as the first message.
 *   3. We display the live `diagnostic` payload from Agent Diagnostiqueur,
 *      then the streaming opening question from Agent Tuteur.
 *   4. "Continue Inquiry" → /inquiry/[sessionId], which loads the chat
 *      with the messages the diagnostic just persisted to Supabase.
 *
 * If the session already has messages, we redirect straight to /inquiry.
 */

import { useEffect, useMemo, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Compass,
  ClipboardCheck,
  Loader2,
  MessageCircleQuestionMark,
  PanelsTopLeft,
  Sparkles,
} from "lucide-react"
import { toast } from "sonner"
import { createClient } from "@/lib/supabase/client"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  buildChatWsUrl,
  parseServerMessage,
  type DiagnosticReport,
} from "@/lib/socra-ws"
import { useUserSettings } from "@/hooks/useUserSettings"
import type { Document, Course } from "@/types"
import type { LearningMode } from "@/lib/socra-ws"


type Phase = "picking" | "thinking" | "diagnosed" | "ready" | "error"

const learningModes: Array<{
  id: LearningMode
  title: string
  description: string
  detail: string
  Icon: typeof Compass
}> = [
  {
    id: "socratic",
    title: "Socratic Dialogue",
    description: "Think it through with a tutor",
    detail: "A short diagnostic sets your starting point, then Socra guides you with course-grounded questions.",
    Icon: MessageCircleQuestionMark,
  },
  {
    id: "explain",
    title: "Explain a Topic",
    description: "Get a clear, cited explanation",
    detail: "Ask about a topic and get a direct explanation grounded in your uploaded course pages.",
    Icon: PanelsTopLeft,
  },
  {
    id: "exercise",
    title: "Practice Exercises",
    description: "Try a course-based question",
    detail: "Ask for a short-answer, multiple-choice, or numerical question grounded in your course.",
    Icon: ClipboardCheck,
  },
]


export default function DiagnosticPage() {
  const params = useParams<{ courseId: string; sessionId: string }>()
  const router = useRouter()
  const { courseId, sessionId } = params

  const [course, setCourse] = useState<Course | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [topic, setTopic] = useState("")
  const [learningMode, setLearningMode] = useState<LearningMode>("socratic")
  const [phase, setPhase] = useState<Phase>("picking")
  const [diagnostic, setDiagnostic] = useState<DiagnosticReport | null>(null)
  const [tutorOpening, setTutorOpening] = useState("")
  const [modeResultReady, setModeResultReady] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const { getActiveConfig } = useUserSettings()

  // ----------------------------------------------------------------
  // Load course + documents (for nicer suggested topics) + bail out if
  // this session already has prior turns.
  // ----------------------------------------------------------------
  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      try {
        const [coursesRes, docsRes, msgsRes] = await Promise.all([
          fetch("/api/courses"),
          fetch(`/api/documents/${courseId}`),
          fetch(`/api/sessions/${sessionId}/messages`),
        ])

        if (cancelled) return

        if (coursesRes.ok) {
          const courses = await coursesRes.json()
          const found = courses.find((c: Course) => c.id === courseId)
          if (found) setCourse(found)
        }
        if (docsRes.ok) setDocuments(await docsRes.json())

        if (msgsRes.ok) {
          const msgs = await msgsRes.json()
          if (Array.isArray(msgs) && msgs.length > 0) {
            // Already has history — skip diagnostic.
            router.replace(`/dashboard/course/${courseId}/inquiry/${sessionId}?mode=${learningMode}`)
          }
        }
      } catch {
        // Non-blocking — the diagnostic flow can still proceed.
      }
    }

    bootstrap()
    return () => {
      cancelled = true
    }
  }, [courseId, sessionId, router, learningMode])

  // Tear down the socket on unmount or before navigation away.
  useEffect(() => {
    return () => {
      const ws = wsRef.current
      if (ws && ws.readyState !== WebSocket.CLOSED) ws.close(1000, "diagnostic unmount")
      wsRef.current = null
    }
  }, [])

  // Suggested topic prompts derived from the uploaded documents.
  const suggestions = useMemo(() => {
    if (documents.length === 0) {
      return [
        "Help me prepare for my next exam",
        "I want to understand the most important concept of my course",
        "Quiz me on the basics of the material",
      ]
    }
    const docNames = documents.slice(0, 3).map((d) =>
      (d.filename || "")
        .replace(/\.pdf$/i, "")
        .replace(/[_-]+/g, " ")
        .trim()
    )
    return docNames
      .filter(Boolean)
      .map((name) => `I want to understand the key ideas in "${name}"`)
  }, [documents])

  // ----------------------------------------------------------------
  // Begin diagnostic — open WS, send the topic, capture diagnostic + opening.
  // ----------------------------------------------------------------
  const beginDiagnostic = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    setErrorMessage(null)
    setDiagnostic(null)
    setTutorOpening("")
    setPhase("thinking")

    let ws: WebSocket
    try {
      ws = new WebSocket(buildChatWsUrl(sessionId))
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to reach the tutor backend"
      setErrorMessage(msg)
      setPhase("error")
      return
    }
    wsRef.current = ws

    ws.addEventListener("open", () => {
      void (async () => {
        try {
          const cfg = getActiveConfig()
          const forwardKey = cfg.provider === "google" || cfg.provider === "xai" ? cfg : undefined
          let accessToken: string | undefined
          if (learningMode === "exercise" || learningMode === "explain") {
            const { data, error } = await createClient().auth.getSession()
            if (error || !data.session?.access_token) {
              throw new Error("Sign in again before requesting course-based practice or explanations.")
            }
            accessToken = data.session.access_token
          }
          if (ws.readyState !== WebSocket.OPEN) return
          ws.send(JSON.stringify({
            message: trimmed,
            courseId,
            sessionId,
            mode: learningMode,
            ...(accessToken ? { accessToken } : {}),
            ...(forwardKey?.apiKey ? { apiKey: forwardKey.apiKey } : {}),
            ...(forwardKey?.provider ? { provider: forwardKey.provider } : {}),
            ...(forwardKey?.model ? { model: forwardKey.model } : {}),
          }))
        } catch (err) {
          setErrorMessage(err instanceof Error ? err.message : "Could not start this learning mode.")
          setPhase("error")
          ws.close()
        }
      })()
    })

    ws.addEventListener("error", () => {
      setErrorMessage(
        "Could not reach the tutor backend. Make sure the Python server is running on " +
          (process.env.NEXT_PUBLIC_BACKEND_WS_URL || "ws://localhost:8000")
      )
      setPhase("error")
    })

    ws.addEventListener("message", (ev) => {
      const parsed = parseServerMessage(typeof ev.data === "string" ? ev.data : "")
      if (!parsed) return

      switch (parsed.type) {
        case "diagnostic":
          setDiagnostic(parsed.content)
          setPhase("diagnosed")
          break
        case "exercise":
        case "explanation":
          setModeResultReady(true)
          break
        case "token":
          setTutorOpening((prev) => prev + parsed.content)
          break
        case "context":
          // Not expected on the first turn, ignore.
          break
        case "done":
          setPhase("ready")
          // Eagerly close — we'll get a fresh socket on the inquiry page.
          ws.close(1000, "diagnostic done")
          break
        case "error":
          setErrorMessage(parsed.content || "Something went wrong")
          setPhase("error")
          break
      }
    })

    ws.addEventListener("close", () => {
      // If we never reached `ready` and have no error, treat as failure.
      setPhase((prev) => (prev === "thinking" || prev === "diagnosed" ? "error" : prev))
      setErrorMessage((prev) => prev ?? null)
    })
  }

  const handleContinue = () => {
    router.push(`/dashboard/course/${courseId}/inquiry/${sessionId}?mode=${learningMode}`)
  }

  const handleStartOver = () => {
    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      wsRef.current.close(1000, "start over")
    }
    wsRef.current = null
    setPhase("picking")
    setDiagnostic(null)
    setTutorOpening("")
    setModeResultReady(false)
    setErrorMessage(null)
  }

  // ----------------------------------------------------------------
  // Render
  // ----------------------------------------------------------------
  return (
    <div className="container mx-auto max-w-4xl px-4 sm:px-6 py-8 sm:py-12 min-h-[calc(100vh-3.5rem)]">
      {/* Back navigation */}
      <Link
        href={`/dashboard/course/${courseId}`}
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to {course?.name || "course"}
      </Link>

      {/* Header */}
      <div className="mb-10">
        <Badge
          variant="outline"
          className="border-tertiary/30 bg-tertiary/10 text-tertiary text-[10px] uppercase tracking-widest mb-4"
        >
          <Sparkles className="h-3 w-3 mr-1.5" />
          {learningMode === "socratic" ? "Socratic Diagnostic" : learningMode === "explain" ? "Explain a Topic" : "Practice Exercises"}
        </Badge>
        <h1 className="font-serif text-3xl sm:text-4xl font-medium tracking-tight mb-3">
          {learningMode === "socratic" ? "Before we begin, let's see where you stand." : learningMode === "explain" ? "Let's explore your topic." : "Let's practice with your course material."}
        </h1>
        <p className="text-muted-foreground text-sm sm:text-base max-w-2xl leading-relaxed">
          {learningMode === "socratic"
            ? "A short diagnostic will set the right starting point for our dialogue. Tell me what you want to explore, and the tutor will open with a question grounded in your course material."
            : learningMode === "explain"
              ? "Tell me what you want to understand. The Explicateur will answer your request directly using your course and cite its source pages."
              : "Tell me what you want to practice. Ask explicitly for multiple-choice or numerical questions; otherwise Socra creates short-answer practice from your course."}
        </p>
      </div>

      {/* Picking phase */}
      {phase === "picking" && (
        <div className="space-y-5">
          <div>
            <p className="mb-3 text-sm font-medium">Choose how you want to study</p>
            <div role="group" aria-label="Learning mode" className="grid gap-3 md:grid-cols-3">
              {learningModes.map(({ id, title, description, Icon }) => {
                const selected = learningMode === id
                return (
                  <button
                    key={id}
                    id={`learning-mode-${id}`}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => setLearningMode(id)}
                    className={`min-h-28 rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary/70 ${
                      selected
                        ? "border-secondary bg-secondary/10 shadow-sm ring-1 ring-secondary/40"
                        : "border-border/60 bg-card/40 hover:border-secondary/40 hover:bg-card"
                    }`}
                  >
                    <span className="mb-3 flex items-center gap-2">
                      <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${selected ? "bg-secondary/15 text-secondary" : "bg-muted text-muted-foreground"}`}>
                        <Icon className="h-4 w-4" />
                      </span>
                      {id === "socratic" && <span className="text-[9px] font-semibold uppercase tracking-wider text-secondary">Default</span>}
                    </span>
                    <span className="block text-sm font-semibold">{title}</span>
                    <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{description}</span>
                  </button>
                )
              })}
            </div>
            <p aria-live="polite" className="mt-3 text-xs leading-relaxed text-muted-foreground">
              {learningModes.find((mode) => mode.id === learningMode)?.detail}
              {learningMode === "socratic" && " Practice and Explain answer directly without the diagnostic."}
            </p>
          </div>
          <PickingPanel
            topic={topic}
            onTopicChange={setTopic}
            onSubmit={() => beginDiagnostic(topic)}
            buttonLabel={learningMode === "socratic" ? "Begin diagnostic" : learningMode === "explain" ? "Explain this topic" : "Create a practice question"}
            suggestions={suggestions}
            onPickSuggestion={(s) => {
              setTopic(s)
              beginDiagnostic(s)
            }}
          />
        </div>
      )}

      {/* Thinking / diagnosed / ready phases */}
      {phase !== "picking" && phase !== "error" && (
        <div className="space-y-6">
          <PromptEcho text={topic} />

          {learningMode === "socratic" ? (
            <>
              <DiagnosticCard diagnostic={diagnostic} loading={phase === "thinking"} />
              <TutorOpeningCard text={tutorOpening} visible={phase === "diagnosed" || phase === "ready"} streaming={phase === "diagnosed"} />
            </>
          ) : (
            <div className="rounded-xl border border-border/40 bg-card/30 p-5 text-sm text-muted-foreground">
              {phase === "thinking"
                ? learningMode === "explain" ? "Preparing your course-grounded explanation…" : "Preparing your verified practice question…"
                : modeResultReady
                  ? learningMode === "explain" ? "Your explanation is ready. Continue to view it with its course citations." : "Your practice question is ready. Continue to view it."
                  : "Your selected learning mode is processing your request."}
            </div>
          )}

          <div className="flex items-center justify-between gap-3 pt-2">
            <Button variant="ghost" size="sm" onClick={handleStartOver}>
              Start over
            </Button>
            <Button
              className="gap-2"
              disabled={phase !== "ready"}
              onClick={handleContinue}
            >
              {phase === "ready" ? learningMode === "socratic" ? "Continue Inquiry" : learningMode === "explain" ? "View Explanation" : "View Practice" : "Preparing your response..."}
              <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {/* Error state */}
      {phase === "error" && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 space-y-4">
          <div className="flex items-start gap-3">
            <div className="h-9 w-9 shrink-0 rounded-md bg-destructive/10 flex items-center justify-center">
              <Compass className="h-4 w-4 text-destructive" />
            </div>
            <div className="space-y-1">
              <h3 className="font-medium text-foreground">
                {learningMode === "exercise"
                  ? "Practice question could not be created"
                  : learningMode === "explain"
                    ? "Explanation could not be prepared"
                    : "Diagnostic could not complete"}
              </h3>
              <p className="text-sm text-muted-foreground">
                {errorMessage || "An unknown error occurred."}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleStartOver}>
              Try again
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                if (errorMessage) toast.warning("Skipping diagnostic")
    router.push(learningMode === "socratic" ? `/dashboard/course/${courseId}/inquiry/${sessionId}` : `/dashboard/course/${courseId}/inquiry/${sessionId}?mode=${learningMode}`)
              }}
            >
              Skip and open inquiry
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}


// ============================================================================
// Sub-components — kept inline so the design stays self-contained
// ============================================================================

function PickingPanel({
  topic,
  onTopicChange,
  onSubmit,
  suggestions,
  onPickSuggestion,
  buttonLabel,
}: {
  topic: string
  onTopicChange: (s: string) => void
  onSubmit: () => void
  suggestions: string[]
  onPickSuggestion: (s: string) => void
  buttonLabel: string
}) {
  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-border/50 bg-card/40 p-5">
        <label
          htmlFor="diagnostic-topic"
          className="block text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2"
        >
          What would you like to explore today?
        </label>
        <textarea
          id="diagnostic-topic"
          value={topic}
          onChange={(e) => onTopicChange(e.target.value)}
          placeholder='e.g. "I want to understand the second law of thermodynamics."'
          rows={3}
          className="w-full resize-none bg-transparent border border-border/40 rounded-lg px-3 py-2.5 text-sm outline-none focus:border-secondary/40 placeholder:text-muted-foreground/50 transition-colors"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              onSubmit()
            }
          }}
        />
        <div className="flex items-center justify-between mt-3">
          <p className="text-[11px] text-muted-foreground/60">
            Tip: press ⌘/Ctrl + Enter to begin.
          </p>
          <Button
            className="gap-2"
            disabled={!topic.trim()}
            onClick={onSubmit}
          >
            <Sparkles className="h-3.5 w-3.5" />
            {buttonLabel}
          </Button>
        </div>
      </div>

      {suggestions.length > 0 && (
        <div>
          <h3 className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-3">
            Suggested starts
          </h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => onPickSuggestion(s)}
                className="text-left rounded-lg border border-border/40 bg-card/30 hover:bg-card/60 hover:border-secondary/30 transition-colors p-3 group"
              >
                <div className="flex items-start gap-2">
                  <BookOpen className="h-4 w-4 mt-0.5 shrink-0 text-secondary/70 group-hover:text-secondary" />
                  <span className="text-sm text-foreground/90">{s}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}


function PromptEcho({ text }: { text: string }) {
  if (!text) return null
  return (
    <div className="rounded-xl border border-border/40 bg-card/30 p-4">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
        You asked
      </p>
      <p className="text-sm text-foreground/90 leading-relaxed">{text}</p>
    </div>
  )
}


function DiagnosticCard({
  diagnostic,
  loading,
}: {
  diagnostic: DiagnosticReport | null
  loading: boolean
}) {
  return (
    <div className="rounded-xl border border-tertiary/20 bg-tertiary/5 p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className="h-7 w-7 rounded-md bg-tertiary/15 flex items-center justify-center">
          <Compass className="h-3.5 w-3.5 text-tertiary" />
        </div>
        <h3 className="text-[10px] font-semibold uppercase tracking-widest text-tertiary">
          Agent Diagnostiqueur
        </h3>
        {loading && (
          <Loader2 className="h-3.5 w-3.5 text-tertiary/70 animate-spin ml-1" />
        )}
      </div>

      {loading || !diagnostic ? (
        <div className="space-y-3">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
                Topic
              </p>
              <p className="text-sm font-medium">{diagnostic.topic}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
                Starting level
              </p>
              <p className="text-sm font-medium capitalize">
                {diagnostic.initial_level}
              </p>
            </div>
          </div>

          {diagnostic.identified_gaps?.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2">
                Likely gaps
              </p>
              <div className="flex flex-wrap gap-1.5">
                {diagnostic.identified_gaps.map((g) => (
                  <Badge
                    key={g}
                    variant="outline"
                    className="border-border/60 bg-muted/30 text-foreground/80 text-[11px] font-normal"
                  >
                    {g}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {diagnostic.prerequisite_concepts?.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2">
                Prerequisites
              </p>
              <div className="flex flex-wrap gap-1.5">
                {diagnostic.prerequisite_concepts.map((p) => (
                  <Badge
                    key={p}
                    variant="outline"
                    className="border-border/60 bg-muted/30 text-foreground/80 text-[11px] font-normal"
                  >
                    {p}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


function TutorOpeningCard({
  text,
  visible,
  streaming,
}: {
  text: string
  visible: boolean
  streaming: boolean
}) {
  if (!visible) return null
  return (
    <div className="rounded-xl border border-secondary/20 bg-secondary/5 p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className="h-7 w-7 rounded-md bg-secondary/15 flex items-center justify-center">
          <Sparkles className="h-3.5 w-3.5 text-secondary" />
        </div>
        <h3 className="text-[10px] font-semibold uppercase tracking-widest text-secondary">
          Agent Tuteur Socratique
        </h3>
        {streaming && !text && (
          <Loader2 className="h-3.5 w-3.5 text-secondary/70 animate-spin ml-1" />
        )}
      </div>
      {text ? (
        <div className="font-serif text-[15px] leading-relaxed text-foreground/90 whitespace-pre-wrap">
          {text}
          {streaming && (
            <span className="inline-block w-1.5 h-4 ml-1 bg-secondary/60 animate-pulse align-middle" />
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}
    </div>
  )
}
