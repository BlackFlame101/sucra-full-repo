"use client"

import { useEffect, useState, useCallback, useMemo, lazy, Suspense } from "react"
import { useParams, useRouter } from "next/navigation"
import { Menu, PanelRightClose, PanelRightOpen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Sidebar } from "@/components/layout/Sidebar"
import { SettingsDialog } from "@/components/settings/SettingsDialog"
import { UploadModal } from "@/components/documents/UploadModal"
import { useSocraChat } from "@/hooks/useSocraChat"
import { useUserSettings } from "@/hooks/useUserSettings"
import {
  adaptSuggestedReadings,
  type ContextPanelReading,
  type EvaluationResult,
} from "@/lib/socra-ws"
import { toast } from "sonner"
import type { Course, Document, Session } from "@/types"
import type { UIMessage } from "ai"

const ChatPanel = lazy(() =>
  import("@/components/chat/ChatPanel").then((m) => ({ default: m.ChatPanel }))
)
const ContextPanel = lazy(() =>
  import("@/components/context-panel/ContextPanel").then((m) => ({ default: m.ContextPanel }))
)

function ChatPanelFallback() {
  return (
    <div className="flex flex-col h-full">
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

export default function InquiryPage() {
  const params = useParams<{ courseId: string; sessionId: string }>()
  const router = useRouter()
  const { courseId, sessionId } = params

  const [course, setCourse] = useState<Course | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [sessionTitle, setSessionTitle] = useState("New Inquiry")
  const [messagesLoading, setMessagesLoading] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [contextOpen, setContextOpen] = useState(false)

  useEffect(() => {
    const lg = window.matchMedia("(min-width: 1024px)")
    const xl = window.matchMedia("(min-width: 1280px)")
    setSidebarOpen(lg.matches)
    setContextOpen(xl.matches)
  }, [])
  const [input, setInput] = useState("")

  const [keyTerms, setKeyTerms] = useState<string[]>([])
  const [suggestedReadings, setSuggestedReadings] = useState<ContextPanelReading[]>([])
  const [contextLoading, setContextLoading] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)

  const handleContext = useCallback((evaluation: EvaluationResult) => {
    if (evaluation.key_terms?.length) setKeyTerms(evaluation.key_terms)
    if (evaluation.suggested_readings?.length) {
      setSuggestedReadings(adaptSuggestedReadings(evaluation.suggested_readings))
    }
    setContextLoading(false)
  }, [])

  const handleChatError = useCallback((err: Error) => {
    toast.error("Tutor backend error", { description: err.message })
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

  const { messages, status, error, sendMessage, setMessages, regenerate } = useSocraChat({
    sessionId,
    courseId,
    llmConfig,
    onContext: handleContext,
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

  // Fetch course, documents, and sessions
  useEffect(() => {
    async function fetchData() {
      try {
        const [coursesRes, docsRes, sessionsRes] = await Promise.all([
          fetch("/api/courses"),
          fetch(`/api/documents/${courseId}`),
          fetch(`/api/sessions/${courseId}`),
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

        if (docsRes.ok) setDocuments(await docsRes.json())
        if (sessionsRes.ok) setSessions(await sessionsRes.json())
      } catch {
        toast.error("Failed to load course data")
      }
    }
    fetchData()
  }, [courseId, router])

  // Load existing messages for this session
  useEffect(() => {
    let cancelled = false

    async function loadMessages() {
      try {
        const res = await fetch(`/api/sessions/${sessionId}/messages`)
        if (!cancelled && res.ok) {
          const dbMessages = await res.json()
          if (Array.isArray(dbMessages) && dbMessages.length > 0) {
            const restored: UIMessage[] = dbMessages.map(
              (m: { id: string; role: string; content: string }) => ({
                id: m.id,
                role: m.role as "user" | "assistant",
                parts: [{ type: "text" as const, text: m.content }],
              })
            )
            setMessages(restored)
          } else {
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
  }, [sessionId, courseId, setMessages, router])

  const handleSendMessage = () => {
    if (!input.trim()) return
    const text = input
    setInput("")
    sendMessage({ text })
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

  const refreshDocuments = async () => {
    try {
      const res = await fetch(`/api/documents/${courseId}`)
      if (res.ok) setDocuments(await res.json())
    } catch { /* non-critical */ }
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Mobile sidebar toggle */}
      <Button
        variant="ghost"
        size="icon"
        className="fixed bottom-4 left-4 z-50 lg:hidden h-10 w-10 rounded-full bg-card border border-border/50 shadow-lg"
        onClick={() => setSidebarOpen(!sidebarOpen)}
      >
        <Menu className="h-4 w-4" />
      </Button>

      {/* Left Sidebar */}
      <aside
        className={`${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        } fixed inset-y-14 left-0 z-40 w-64 transition-transform duration-200 lg:relative lg:inset-y-0 lg:translate-x-0 lg:w-64 shrink-0`}
      >
        <Sidebar
          courseName={course?.name || "Loading..."}
          courseId={courseId}
          documents={documents}
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
          className="fixed inset-0 z-30 bg-background/80 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Center Chat Panel */}
      <main className="flex-1 min-w-0">
        <Suspense fallback={<ChatPanelFallback />}>
          <ChatPanel
            sessionTitle={sessionTitle}
            messages={messages}
            input={input}
            status={status}
            messagesLoading={messagesLoading}
            error={error}
            onInputChange={setInput}
            onSubmit={handleSendMessage}
            onRetry={regenerate}
            onAttach={() => setUploadOpen(true)}
          />
        </Suspense>
      </main>

      {/* Context panel toggle */}
      <Button
        variant="ghost"
        size="icon"
        className="fixed bottom-4 right-4 z-50 xl:hidden h-10 w-10 rounded-full bg-card border border-border/50 shadow-lg"
        onClick={() => setContextOpen(!contextOpen)}
      >
        {contextOpen ? (
          <PanelRightClose className="h-4 w-4" />
        ) : (
          <PanelRightOpen className="h-4 w-4" />
        )}
      </Button>

      {/* Right Context Panel */}
      <aside
        className={`${
          contextOpen ? "translate-x-0" : "translate-x-full"
        } fixed inset-y-14 right-0 z-40 w-72 overflow-hidden transition-transform duration-200 xl:relative xl:inset-y-0 xl:translate-x-0 xl:w-72 shrink-0`}
      >
        <Suspense fallback={<ContextPanelFallback />}>
          <ContextPanel
            keyTerms={keyTerms}
            suggestedReadings={suggestedReadings}
            isLoading={contextLoading}
          />
        </Suspense>
      </aside>

      {/* Context panel overlay on mobile */}
      {contextOpen && (
        <div
          className="fixed inset-0 z-30 bg-background/80 backdrop-blur-sm xl:hidden"
          onClick={() => setContextOpen(false)}
        />
      )}

      <UploadModal
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        courseId={courseId}
        onUploadComplete={refreshDocuments}
      />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  )
}
