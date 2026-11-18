"use client"

import { useEffect, useState, useCallback, useMemo, useRef, lazy, Suspense } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import { Menu, TriangleAlert, Settings } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Sidebar } from "@/components/layout/Sidebar"
import { SettingsDialog } from "@/components/settings/SettingsDialog"
import { pdfPageUrl } from "@/components/documents/PdfCitation"
import { UploadModal } from "@/components/documents/UploadModal"
import { SaveResponseDialog, type CaptureTarget } from "@/components/notebook/SaveResponseDialog"
import { useSocraChat } from "@/hooks/useSocraChat"
import { useAuth } from "@/hooks/useAuth"
import { usePdfPolling } from "@/hooks/usePdfPolling"
import { useUserSettings } from "@/hooks/useUserSettings"
import {
  adaptSuggestedReadings,
  type ContextPanelReading,
  type EvaluationResult,
} from "@/lib/socra-ws"
import type { CourseContextMaterial } from "@/components/context-panel/ContextPanel"
import { toast } from "sonner"
import type { Course, Session } from "@/types"
import type { UIMessage } from "ai"
import type { LearningMode, PublicCorrection, PublicExercise, PublicSolution } from "@/lib/socra-ws"
import { educationalCitations, isEducationalDocument } from "@/lib/educational-document"
import type { ExplanationPayload } from "@/lib/socra-ws"

const ChatPanel = lazy(() =>
  import("@/components/chat/ChatPanel").then((m) => ({ default: m.ChatPanel }))
)
const ContextPanel = lazy(() =>
  import("@/components/context-panel/ContextPanel").then((m) => ({ default: m.ContextPanel }))
)

function ChatPanelFallback() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border/40 px-6 py-3">
        <Skeleton className="h-6 w-64" />
      </div>
      <div className="flex-1 flex items-center justify-center">
        <Skeleton className="h-16 w-16 rounded-2xl" />
      </div>
    </div>
  )
}

function ContextPanelFallback() {
  return (
    <div className="border-l border-border/40 bg-card/20 h-full p-4 space-y-6">
      <Skeleton className="h-3 w-32" />
      <div className="flex flex-wrap gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-6 w-20 rounded-full" />
        ))}
      </div>
      <Skeleton className="h-3 w-32 mt-4" />
      <Skeleton className="h-20 w-full rounded-xl" />
    </div>
  )
}

function visibleMessageText(role: string, content: string): string {
  if (role !== "user") return content
  const isGeneratedQuestionAction =
    content.startsWith("Give me another short-answer question from anywhere in my course material.") ||
    /^Give me a different short-answer question about [\s\S]+\. Avoid repeating the previous question\.$/.test(content)
  return isGeneratedQuestionAction ? "Generate another question" : content
}

function isLearningMode(value: unknown): value is LearningMode {
  return value === "socratic" || value === "exercise" || value === "explain"
}

function storedModeKey(sessionId: string) {
  return `socra:inquiry-mode:${sessionId}`
}

export default function InquiryPage() {
  const { user } = useAuth()
  const params = useParams<{ courseId: string; sessionId: string }>()
  const router = useRouter()
  const searchParams = useSearchParams()
  const notebookId = searchParams.get("note")
  const { courseId, sessionId } = params

  const [course, setCourse] = useState<Course | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [sessionTitle, setSessionTitle] = useState("New Inquiry")
  const [sessionSavedToLibrary, setSessionSavedToLibrary] = useState(false)
  const [savingSessionToLibrary, setSavingSessionToLibrary] = useState(false)
  const [language, setLanguage] = useState<"fr" | "en">("fr")
  const [messagesLoading, setMessagesLoading] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [contextOpen, setContextOpen] = useState(false)
  const sidebarToggle = useRef<HTMLButtonElement>(null)
  const contextToggle = useRef<HTMLButtonElement>(null)
  const contextClose = useRef<HTMLButtonElement>(null)
  const focusContextOnOpen = useRef(false)
  const [sourcePage, setSourcePage] = useState<{ id: string; page: number; name: string } | null>(null)
  const [learningMode, setLearningMode] = useState<LearningMode>(() =>
    searchParams.get("mode") === "exercise" ? "exercise" : searchParams.get("mode") === "explain" ? "explain" : "socratic"
  )
  const [exercise, setExercise] = useState<PublicExercise | null>(null)
  const [correction, setCorrection] = useState<PublicCorrection | null>(null)
  const [solution, setSolution] = useState<PublicSolution | null>(null)
  const [explanation, setExplanation] = useState<ExplanationPayload | null>(null)

  useEffect(() => {
    let cancelled = false
    setSessionSavedToLibrary(false)
    fetch(`/api/library/sessions/${encodeURIComponent(sessionId)}`)
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => { if (!cancelled) setSessionSavedToLibrary(payload?.saved === true) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [sessionId])

  useEffect(() => {
    const lg = window.matchMedia("(min-width: 1024px)")
    const xl = window.matchMedia("(min-width: 1280px)")
    const resetSidebar = ({ matches }: { matches: boolean }) => {
      setSidebarOpen(false)
      if (!matches && document.activeElement?.closest("#inquiry-sidebar")) sidebarToggle.current?.focus()
    }
    const syncLayout = ({ matches }: { matches: boolean }) => {
      const focused = document.activeElement
      setSidebarOpen(false)
      setContextOpen(matches)
      if (focused?.closest("#inquiry-context") && !matches) contextToggle.current?.focus()
    }
    syncLayout(xl)
    lg.addEventListener("change", resetSidebar)
    xl.addEventListener("change", syncLayout)
    return () => {
      lg.removeEventListener("change", resetSidebar)
      xl.removeEventListener("change", syncLayout)
    }
  }, [])
  useEffect(() => {
    if (!contextOpen || !focusContextOnOpen.current) return
    const frame = requestAnimationFrame(() => {
      contextClose.current?.focus({ preventScroll: true })
      if (document.activeElement === contextClose.current) focusContextOnOpen.current = false
    })
    return () => cancelAnimationFrame(frame)
  }, [contextOpen])
  const [input, setInput] = useState("")

  const [keyTerms, setKeyTerms] = useState<string[]>([])
  const [suggestedReadings, setSuggestedReadings] = useState<ContextPanelReading[]>([])
  const [courseMaterials, setCourseMaterials] = useState<CourseContextMaterial[]>([])
  const [contextLoading, setContextLoading] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [apiKeyIssue, setApiKeyIssue] = useState<{ code: string; message: string } | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [capture, setCapture] = useState<CaptureTarget | null>(null)

  const materialRequest = useRef(0)
  const refreshMaterials = useCallback(async (signal?: AbortSignal) => {
    const request = ++materialRequest.current
    try {
      const response = await fetch(`/api/documents/${courseId}/context`, { signal })
      if (response.ok) {
        const materials: CourseContextMaterial[] = await response.json()
        if (signal?.aborted || request !== materialRequest.current) return
        setCourseMaterials(materials)
        return materials.some((material) => material.processing)
      }
      if (response.status === 401 || response.status === 403 || response.status === 404) return false
    } catch { /* Keep the last successful snapshot. */ }
  }, [courseId])

  usePdfPolling(courseMaterials.some((material) => material.processing), refreshMaterials)

  const handleContext = useCallback((evaluation: EvaluationResult) => {
    setKeyTerms(evaluation.key_terms ?? [])
    setSuggestedReadings(adaptSuggestedReadings(evaluation.suggested_readings))
    setContextLoading(false)
  }, [])

  const handleChatError = useCallback((err: Error) => {
    const code = (err as Error & { code?: string }).code
    if (code?.startsWith("API_")) {
      setApiKeyIssue({ code, message: err.message })
      return
    }
    if (code === "GROQ_STRUCTURED_OUTPUT_FAILED") {
      toast.error("Groq could not complete a valid answer", { description: err.message })
      return
    }
    toast.error("Tutor backend error", { description: err.message })
  }, [])

  const handleExercise = useCallback((value: PublicExercise) => {
    setLearningMode("exercise")
    window.localStorage.setItem(storedModeKey(sessionId), "exercise")
    setExplanation(null)
    setExercise(value)
    setCorrection(null)
    setSolution(null)
    setKeyTerms([value.concept])
    setSuggestedReadings(value.citations.map((citation) => ({
      documentId: citation.document_id,
      documentName: citation.filename,
      pageNumber: citation.page_number ?? 0,
      section: citation.excerpt || value.concept,
    })))
  }, [sessionId])

  const handleExplanation = useCallback((value: ExplanationPayload) => {
    setLearningMode("explain")
    window.localStorage.setItem(storedModeKey(sessionId), "explain")
    setExplanation(value)
    setExercise(null)
    setCorrection(null)
    setSolution(null)
    const citations = isEducationalDocument(value) ? educationalCitations(value) : value.citations
    const headings = isEducationalDocument(value) ? value.sections.map((section) => section.title)
      : value.sections?.map((section) => section.heading) ?? []
    setKeyTerms(headings.filter(Boolean).slice(0, 8))
    setSuggestedReadings(citations.map((citation) => ({
      documentId: citation.document_id,
      documentName: citation.filename,
      pageNumber: citation.page_number ?? 0,
      section: citation.excerpt || (isEducationalDocument(value) ? value.title : value.definition),
    })))
  }, [sessionId])

  const handleCorrection = useCallback((value: PublicCorrection) => {
    setCorrection(value)
    setKeyTerms(value.criterion_feedback.map((criterion) => criterion.criterion).slice(0, 8))
    setSuggestedReadings(value.citations.map((citation) => ({
      documentId: citation.document_id,
      documentName: citation.filename,
      pageNumber: citation.page_number ?? 0,
      section: citation.excerpt || "Exercise feedback source",
    })))
  }, [])

  const handleSolution = useCallback((value: PublicSolution) => {
    setSolution(value)
  }, [])

  const { getActiveConfig } = useUserSettings()
  const activeConfig = getActiveConfig()
  // Recompute the llmConfig object only when the meaningful pieces change so
  // we don't trigger reconnects on every render.
  const llmConfig = useMemo(
    () => ({
      apiKey: activeConfig.apiKey,
      provider: activeConfig.provider,
      model: activeConfig.model,
    }),
    [activeConfig.apiKey, activeConfig.provider, activeConfig.model]
  )

  const { messages, explanationTurns, status, progress, connection, stop, error, sendMessage, runUnitAction,
    submitAttempt, revealSolution, setMessages, regenerate, canRegenerate } = useSocraChat({
    sessionId,
    courseId,
    recoverInterrupted: !messagesLoading,
    language,
    llmConfig,
    onContext: handleContext,
    onExercise: handleExercise,
    onExplanation: handleExplanation,
    onCorrection: handleCorrection,
    onSolution: handleSolution,
    onError: handleChatError,
  })

  // Show context-panel skeletons while a substantive turn is being analysed.
  useEffect(() => {
    if (status === "streaming" || status === "submitted") {
      // Only flag context as loading if the user just sent something substantive.
      const last = [...messages].reverse().find((m) => m.role === "user")
      const lastText = last?.parts
        .filter((p): p is { type: "text"; text: string } => p.type === "text")
        .map((p) => p.text)
        .join("") ?? ""
      if (lastText.trim().split(/\s+/).length >= 8) {
        setContextLoading(true)
      }
    } else if (status === "ready" || status === "error") {
      setContextLoading(false)
    }
  }, [status, messages])

  // Fetch course, materials, and sessions.
  useEffect(() => {
    const controller = new AbortController()
    async function fetchData() {
      try {
        const [coursesRes, sessionsRes] = await Promise.all([
          fetch(`/api/courses?course=${encodeURIComponent(courseId)}`, { signal: controller.signal }),
          fetch(`/api/sessions/${courseId}`, { signal: controller.signal }),
        ])

        if (coursesRes.ok) {
          const courses = await coursesRes.json()
          const found = courses.find((c: Course) => c.id === courseId)
          if (found) setCourse(found)
          else {
            router.push("/dashboard")
            return
          }
        }

        if (sessionsRes.ok) setSessions(await sessionsRes.json())
      } catch {
        if (!controller.signal.aborted) toast.error("Failed to load course data")
      }
    }
    void fetchData()
    void refreshMaterials(controller.signal)
    return () => controller.abort()
  }, [courseId, refreshMaterials, router])

  // Load existing messages for this session
  useEffect(() => {
    let cancelled = false

    async function loadMessages() {
      setMessagesLoading(true)
      setMessages([])
      setExercise(null)
      setCorrection(null)
      setSolution(null)
      setExplanation(null)
      setKeyTerms([])
      setSuggestedReadings([])
      const queryMode = new URLSearchParams(window.location.search).get("mode")
      const savedMode = window.localStorage.getItem(storedModeKey(sessionId))
      setLearningMode(isLearningMode(queryMode) ? queryMode : isLearningMode(savedMode) ? savedMode : "socratic")
      try {
        const res = await fetch(`/api/sessions/${sessionId}/messages`)
        if (!cancelled && res.ok) {
          const dbMessages = await res.json()
          if (Array.isArray(dbMessages) && dbMessages.length > 0) {
            const restored: UIMessage[] = dbMessages.map(
              (m: { id: string; role: string; content: string; metadata?: Record<string, unknown> }) => ({
                id: m.id,
                role: m.role as "user" | "assistant",
                parts: [{ type: "text" as const, text: visibleMessageText(m.role, m.content) }],
                metadata: { ...m.metadata, persisted: m.role === "assistant" },
              })
            )
            setMessages(restored)
            const latestMode = [...dbMessages].reverse().find(
              (m: { metadata?: Record<string, unknown> }) => isLearningMode(m.metadata?.learning_mode)
            )?.metadata?.learning_mode
            const latestAssistantMetadata = (key: string) => [...dbMessages].reverse().find(
              (m: { role: string; metadata?: Record<string, unknown> }) =>
                m.role === "assistant" && m.metadata?.[key]
            )?.metadata?.[key]
            const context = latestAssistantMetadata("course_context") as EvaluationResult | undefined
            if (context) handleContext(context)
            else {
              void fetch(`/api/sessions/${sessionId}/study-context`).then((response) => response.ok ? response.json() : null)
                .then((value) => { if (!cancelled && value) setKeyTerms((current) => current.length ? current : value.key_terms) })
                .catch(() => {})
            }
            const restoredExercise = latestAssistantMetadata("exercise")
            const restoredExplanation = latestAssistantMetadata("explanation")
            const restoredCorrection = latestAssistantMetadata("correction")
            const restoredSolution = latestAssistantMetadata("solution")
            if (!isLearningMode(queryMode) && !isLearningMode(savedMode) && isLearningMode(latestMode)) {
              setLearningMode(latestMode)
              window.localStorage.setItem(storedModeKey(sessionId), latestMode)
            } else {
              // Infer a useful mode from older messages written before mode metadata was saved.
              const latestModeArtifact = [...dbMessages].reverse().find(
                (m: { role: string; metadata?: Record<string, unknown> }) =>
                  m.role === "assistant" && (m.metadata?.exercise || m.metadata?.correction || m.metadata?.explanation)
              )
              if (!isLearningMode(queryMode) && !isLearningMode(savedMode) && (latestModeArtifact?.metadata?.exercise || latestModeArtifact?.metadata?.correction)) {
                setLearningMode("exercise")
                window.localStorage.setItem(storedModeKey(sessionId), "exercise")
              } else if (!isLearningMode(queryMode) && !isLearningMode(savedMode) && latestModeArtifact?.metadata?.explanation) {
                setLearningMode("explain")
                window.localStorage.setItem(storedModeKey(sessionId), "explain")
              }
            }
            if (restoredExercise) setExercise(restoredExercise as PublicExercise)
            if (restoredExplanation) setExplanation(restoredExplanation as ExplanationPayload)
            if (restoredCorrection) setCorrection(restoredCorrection as PublicCorrection)
            if (restoredSolution) setSolution(restoredSolution as PublicSolution)
          } else if (!notebookId) {
            // Brand new session — push the user back through the diagnostic.
            router.replace(
              `/dashboard/course/${courseId}/inquiry/${sessionId}/diagnostic`
            )
            return
          }
        }

        const sessionsRes = await fetch(`/api/sessions/${courseId}`)
        if (!cancelled && sessionsRes.ok) {
          const allSessions = await sessionsRes.json()
          const current = allSessions.find((s: Session) => s.id === sessionId)
          if (current?.title) setSessionTitle(current.title)
          if (current?.language === "fr" || current?.language === "en") setLanguage(current.language)
          setSessions(allSessions)
        }
      } catch {
        // Session might be new or backend unavailable.
      } finally {
        if (!cancelled) setMessagesLoading(false)
      }
    }

    loadMessages()
    return () => {
      cancelled = true
    }
  }, [sessionId, courseId, setMessages, router, handleContext, notebookId])

  const handleSendMessage = () => {
    if (!input.trim()) return
    const text = input
    setInput("")
    if (learningMode === "exercise") setExercise(null)
    if (learningMode === "exercise") {
      setCorrection(null)
      setSolution(null)
    }
    sendMessage({ text, mode: learningMode, ...(notebookId ? { notebook: { id: notebookId, action: learningMode === "exercise" ? "quiz" : "ask" } as const } : {}) })
  }

  const handleLanguageChange = async (nextLanguage: "fr" | "en") => {
    const response = await fetch(`/api/sessions/update/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: nextLanguage }),
    })
    if (!response.ok) {
      toast.error("Could not save the response language")
      return
    }
    setLanguage(nextLanguage)
    setSessions((previous) => previous.map((session) => session.id === sessionId ? { ...session, language: nextLanguage } : session))
  }

  const handleNextExercise = () => {
    if (!exercise || status !== "ready") return
    setLearningMode("exercise")
    window.localStorage.setItem(storedModeKey(sessionId), "exercise")
    replaceInquiryMode("exercise")
    setExercise(null)
    setCorrection(null)
    setSolution(null)
    sendMessage({
      text: "Generate another question. Keep the scope of my most recent specific request for exercise questions, if any; do not infer a narrower scope from the previous exercise's generated concept. Avoid repeating recent questions.",
      displayText: "Generate another question",
      mode: "exercise",
      ...(notebookId ? { notebook: { id: notebookId, action: "quiz" } as const } : {}),
    })
  }

  const handleSubmitAttempt = (answer: string, usedHints: number) => {
    if (!exercise || status !== "ready") return
    submitAttempt({ exerciseId: exercise.id, answer, hintsUsed: usedHints })
  }

  const handleRevealSolution = () => {
    if (!exercise || !correction || solution || status !== "ready") return
    revealSolution(exercise.id)
  }

  function replaceInquiryMode(mode: LearningMode) {
    const path = `/dashboard/course/${courseId}/inquiry/${sessionId}`
    const query = new URLSearchParams()
    if (notebookId) query.set("note", notebookId)
    if (mode !== "socratic") query.set("mode", mode)
    router.replace(query.size ? `${path}?${query}` : path)
  }

  const handleLearningModeChange = (mode: LearningMode) => {
    setLearningMode(mode)
    window.localStorage.setItem(storedModeKey(sessionId), mode)
    replaceInquiryMode(mode)
  }

  const handleDiscussExplanation = (question: string) => {
    setLearningMode("socratic")
    window.localStorage.setItem(storedModeKey(sessionId), "socratic")
    replaceInquiryMode("socratic")
    setInput("")
    sendMessage({ text: question, mode: "socratic", ...(notebookId ? { notebook: { id: notebookId, action: "ask" } as const } : {}) })
  }

  const saveLibraryItem = async (itemType: "explanation" | "exercise", title: string, content: Record<string, unknown>, sourceDocumentId?: string, sourcePage?: number) => {
    const response = await fetch("/api/library", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_type: itemType, title, content: { ...content, session_id: sessionId }, course_id: courseId, source_document_id: sourceDocumentId, source_page: sourcePage }),
    })
    const payload = await response.json()
    if (!response.ok) { toast.error("Could not save to Library", { description: payload.error }); return }
    toast.success("Saved to Library")
  }

  const saveInquiryToLibrary = async () => {
    setSavingSessionToLibrary(true)
    try {
      const response = await fetch(`/api/library/sessions/${encodeURIComponent(sessionId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_type: "inquiry" }),
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(payload?.error || "Could not save this inquiry to your Library.")
      setSessionSavedToLibrary(true)
      toast.success("Saved to Library", { description: "This inquiry transcript is ready to revisit." })
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not save this inquiry to your Library.")
    } finally {
      setSavingSessionToLibrary(false)
    }
  }

  const handleSaveExplanationToLibrary = (value: ExplanationPayload, messageId: string) => {
    const source = (isEducationalDocument(value) ? educationalCitations(value) : value.citations)[0]
    const title = isEducationalDocument(value) ? value.title : value.sections?.[0]?.heading || value.definition.slice(0, 90)
    void saveLibraryItem("explanation", title, { message_id: messageId }, source?.document_id, source?.page_number ?? undefined)
  }

  const handleSaveExerciseToLibrary = (value: PublicCorrection, answer: PublicSolution) => {
    const source = value.citations[0]
    void saveLibraryItem("exercise", `Solved exercise ${answer.exercise_id.slice(0, 8)}`, { correction: value, solution: answer }, source?.document_id, source?.page_number ?? undefined)
  }

  const handleNewInquiry = async () => {
    try {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ courseId, title: "New Inquiry" }),
      })
      if (res.ok) {
        const session = await res.json()
        router.push(
          `/dashboard/course/${courseId}/inquiry/${session.id}/diagnostic`
        )
      }
    } catch {
      toast.error("Failed to create inquiry")
    }
  }

  const handleRenameSession = async (sid: string, newTitle: string) => {
    try {
      const res = await fetch(`/api/sessions/update/${sid}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle }),
      })
      if (res.ok) {
        setSessions((prev) =>
          prev.map((s) => (s.id === sid ? { ...s, title: newTitle } : s))
        )
        if (sid === sessionId) setSessionTitle(newTitle)
        toast.success("Inquiry renamed")
      }
    } catch {
      toast.error("Failed to rename inquiry")
    }
  }

  const closeContext = () => {
    focusContextOnOpen.current = false
    setContextOpen(false)
    contextToggle.current?.focus()
  }

  const closeSidebar = () => {
    setSidebarOpen(false)
    sidebarToggle.current?.focus()
  }

  const refreshDocuments = () => { void refreshMaterials() }

  return (
    <div className="relative isolate flex h-full min-h-0 overflow-hidden" onKeyDown={(event) => {
      if (event.key === "Escape" && event.target instanceof Element) {
        const plan = event.target.closest<HTMLDetailsElement>("details[data-explanation-plan][open]")
        if (plan && (!contextOpen || window.matchMedia("(min-width: 1280px)").matches)) {
          plan.open = false
          plan.querySelector("summary")?.focus()
        } else if (contextOpen) closeContext()
        else if (sidebarOpen) closeSidebar()
      }
    }}>
      {/* Mobile sidebar toggle */}
      <Button
        variant="ghost"
        size="icon"
        ref={sidebarToggle}
        aria-label="Toggle course navigation"
        aria-expanded={sidebarOpen}
        aria-controls="inquiry-sidebar"
        className="absolute bottom-4 left-4 z-50 lg:hidden h-10 w-10 rounded-full bg-card border border-border/50 shadow-lg"
        onClick={() => {
          if (sidebarOpen) closeSidebar()
          else {
            setContextOpen(false)
            setSidebarOpen(true)
          }
        }}
      >
        <Menu className="h-4 w-4" />
      </Button>

      {/* Left Sidebar */}
      <aside id="inquiry-sidebar" aria-label="Course navigation"
        className={`${
          sidebarOpen ? "visible translate-x-0" : "invisible -translate-x-full lg:visible"
        } absolute inset-y-0 left-0 z-40 w-64 bg-background transition-transform duration-200 motion-reduce:transition-none lg:relative lg:translate-x-0 shrink-0`}
      >
        <Sidebar
          courseName={course?.name || "Loading..."}
          courseId={courseId}
          documents={courseMaterials.map(({ documentId, filename }) => ({ id: documentId, filename }))}
          sessions={sessions}
          currentSessionId={sessionId}
          onNewInquiry={handleNewInquiry}
          onSettingsOpen={() => setSettingsOpen(true)}
          onRenameSession={handleRenameSession}
        />
      </aside>

      {/* Sidebar overlay on mobile */}
      {sidebarOpen && (
        <div
          className="absolute inset-0 z-30 bg-background/80 backdrop-blur-sm lg:hidden"
          onClick={closeSidebar}
        />
      )}

      {/* Center Chat Panel */}
      <section aria-label="Inquiry chat" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden" onClickCapture={(event) => {
        if (!(event.target instanceof Element) || window.matchMedia("(min-width: 1280px)").matches) return
        const plan = event.target.closest("details[data-explanation-plan]:not([open]) > summary")
        if (plan) {
          setSidebarOpen(false)
          setContextOpen(false)
        }
      }}>
        {apiKeyIssue && (
          <div role="alert" className="mx-4 mt-4 flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-foreground sm:mx-6">
            <div className="flex items-start gap-3">
              <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
              <div><p className="font-semibold">{apiKeyIssue.code === "API_KEY_QUOTA_EXCEEDED" ? "AI API key usage limit reached" : apiKeyIssue.code === "API_KEY_INVALID" ? "AI API key was rejected" : apiKeyIssue.code === "API_RATE_LIMITED" ? "AI provider is rate-limiting requests" : "AI API key access problem"}</p><p className="mt-1 text-muted-foreground">{apiKeyIssue.message}</p></div>
            </div>
            <Button size="sm" onClick={() => setSettingsOpen(true)}><Settings className="mr-2 h-4 w-4" />Open Settings</Button>
          </div>
        )}
        <Suspense fallback={<ChatPanelFallback />}>
          <ChatPanel
            sessionTitle={sessionTitle}
            language={language}
            onLanguageChange={(value) => void handleLanguageChange(value)}
            messages={messages}
            explanationTurns={explanationTurns}
            courseMaterials={courseMaterials}
            input={input}
            status={status}
            progress={progress}
            connection={connection}
            onStop={stop}
            contextOpen={contextOpen}
            contextToggleRef={contextToggle}
            onToggleContext={() => {
              if (contextOpen) closeContext()
              else {
                setSidebarOpen(false)
                focusContextOnOpen.current = true
                setContextOpen(true)
              }
            }}
            messagesLoading={messagesLoading}
            error={error}
            onInputChange={setInput}
            onSubmit={handleSendMessage}
            onRetry={regenerate}
            canRegenerate={canRegenerate}
            onAttach={() => setUploadOpen(true)}
            learningMode={learningMode}
            onLearningModeChange={handleLearningModeChange}
            exercise={exercise}
            onNextExercise={handleNextExercise}
            onSubmitAttempt={handleSubmitAttempt}
            correction={correction}
            solution={solution}
            onRevealSolution={handleRevealSolution}
            explanation={explanation}
            onDiscussExplanation={handleDiscussExplanation}
            onContinueCourse={(from, requestId, label) => {
              sendMessage({ text: label, mode: "explain", continuation: { from, requestId } })
            }}
            onUnitAction={runUnitAction}
            onSaveExplanationToLibrary={handleSaveExplanationToLibrary}
            explanationOwnerId={user?.id}
            onCaptureResponse={setCapture}
            sourceMessageId={searchParams.get("message")}
            onSaveExerciseToLibrary={handleSaveExerciseToLibrary}
            onSaveSessionToLibrary={() => void saveInquiryToLibrary()}
            sessionSavedToLibrary={sessionSavedToLibrary}
            savingSessionToLibrary={savingSessionToLibrary}
          />
        </Suspense>
      </section>

      {/* Right Context Panel */}
      <aside id="inquiry-context" aria-label="Course context" inert={!contextOpen}
        onTransitionEnd={(event) => {
          if (event.target !== event.currentTarget || !contextOpen || !focusContextOnOpen.current) return
          focusContextOnOpen.current = false
          contextClose.current?.focus({ preventScroll: true })
        }}
        className={`${
          contextOpen ? (sourcePage ? "translate-x-0 xl:w-[min(40vw,44rem)] xl:border-l" : "translate-x-0 xl:w-72 xl:border-l") : "invisible translate-x-full xl:visible xl:translate-x-0 xl:w-0 xl:border-l-0"
        } absolute inset-y-0 right-0 z-40 w-72 min-w-0 max-w-full overflow-hidden border-border/40 bg-background transition-[transform,width] duration-200 motion-reduce:transition-none xl:relative xl:shrink-0`}
      >
        <div className={`relative h-full overflow-hidden ${sourcePage ? "w-full" : "w-72"}`}>
          <Button ref={contextClose} size="sm" variant="ghost" onClick={closeContext}
            className="absolute right-2 top-1 z-10 xl:sr-only xl:focus:not-sr-only" aria-label="Close course context">Close</Button>
          {sourcePage ? <div className="flex h-full flex-col border-l border-border">
            <div className="flex items-center justify-between gap-2 border-b p-3">
              <Button size="sm" variant="outline" onClick={() => setSourcePage(null)}>Back to context</Button>
              <a href={pdfPageUrl(sourcePage.id, sourcePage.page)} target="_blank" rel="noopener noreferrer" className="mr-12 text-sm text-secondary underline xl:mr-0">Open PDF</a>
            </div>
            <iframe key={`${sourcePage.id}:${sourcePage.page}`} title={`${sourcePage.name}, page ${sourcePage.page}`}
              className="min-h-0 flex-1 bg-card" src={pdfPageUrl(sourcePage.id, sourcePage.page)} referrerPolicy="no-referrer" />
          </div> : <Suspense fallback={<ContextPanelFallback />}>
            <ContextPanel
              keyTerms={keyTerms}
              suggestedReadings={suggestedReadings}
              courseMaterials={courseMaterials}
              isLoading={contextLoading}
              onOpenPage={(id, page, name) => setSourcePage({ id, page, name })}
              onProcessingChange={refreshDocuments}
            />
          </Suspense>}
        </div>
      </aside>

      {/* Context panel overlay on mobile */}
      {contextOpen && (
        <div
          className="absolute inset-0 z-30 bg-background/80 backdrop-blur-sm xl:hidden"
          onClick={closeContext}
        />
      )}

      <UploadModal
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        courseId={courseId}
        onUploadComplete={refreshDocuments}
      />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} onSaved={() => setApiKeyIssue(null)} />
      {capture && <SaveResponseDialog target={capture} courseId={courseId} sessionId={sessionId}
        onClose={() => setCapture(null)} onSaved={(id) => {
          setCapture(null)
          toast.success("Saved to Notebook", { action: { label: "Open note", onClick: () => router.push(`/dashboard/notebook?note=${id}`) } })
        }} />}
    </div>
  )
}
