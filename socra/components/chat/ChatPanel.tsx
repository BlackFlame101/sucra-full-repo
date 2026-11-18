"use client"

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type MouseEvent } from "react"
import { Bookmark, NotebookPen, RotateCcw, ArrowDown, PanelRightClose, PanelRightOpen } from "lucide-react"
import type { CaptureTarget } from "@/components/notebook/SaveResponseDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MessageList } from "./MessageList"
import { ChatInput } from "./ChatInput"
import { ExerciseCard } from "./ExerciseCard"
import { ExerciseFeedbackCard } from "./ExerciseFeedbackCard"
import { ExplanationCard } from "./ExplanationCard"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { isEducationalDocument } from "@/lib/educational-document"
import type { LearningMode, PublicCorrection, PublicExercise, ExplanationPayload, PublicSolution } from "@/lib/socra-ws"
import { supportedUnitActions, type ExplanationTurn, type UnitAction } from "@/lib/explanation-v2"
import { LiveExplanation } from "@/components/chat/LiveExplanation"
import type { CourseContextMaterial } from "@/components/context-panel/ContextPanel"
import type { UIMessage } from "ai"

interface ChatPanelProps {
  sessionTitle: string
  language: "fr" | "en"
  onLanguageChange: (language: "fr" | "en") => void
  messages: UIMessage[]
  input: string
  status: string
  progress?: string
  connection?: string
  onStop?: () => void
  messagesLoading: boolean
  error?: Error | null
  onInputChange: (value: string) => void
  onSubmit: () => void
  onRetry?: () => void
  canRegenerate?: boolean
  onAttach?: () => void
  learningMode: LearningMode
  onLearningModeChange: (mode: LearningMode) => void
  exercise: PublicExercise | null
  onNextExercise: () => void
  onSubmitAttempt: (answer: string, hintsUsed: number) => void
  correction: PublicCorrection | null
  solution: PublicSolution | null
  onRevealSolution: () => void
  explanation: ExplanationPayload | null
  onDiscussExplanation: (question: string) => void
  onContinueCourse: (from: string, requestId: string, label: string) => void
  onUnitAction?: (from: string, action: UnitAction, label: string) => void
  explanationTurns?: ReadonlyMap<string, ExplanationTurn>
  courseMaterials?: CourseContextMaterial[]
  onSaveExplanationToLibrary: (explanation: ExplanationPayload, messageId: string) => void
  explanationOwnerId?: string
  onCaptureResponse: (target: CaptureTarget) => void
  sourceMessageId?: string | null
  onSaveExerciseToLibrary: (correction: PublicCorrection, solution: PublicSolution) => void
  onSaveSessionToLibrary: () => void
  sessionSavedToLibrary: boolean
  savingSessionToLibrary: boolean
  contextOpen: boolean
  onToggleContext: () => void
  contextToggleRef?: React.Ref<HTMLButtonElement>
}

export function ChatPanel({
  sessionTitle,
  language,
  onLanguageChange,
  messages,
  input,
  status,
  progress,
  connection,
  onStop,
  messagesLoading,
  error,
  onInputChange,
  onSubmit,
  onRetry,
  canRegenerate,
  onAttach,
  learningMode,
  onLearningModeChange,
  exercise,
  onNextExercise,
  onSubmitAttempt,
  correction,
  solution,
  onRevealSolution,
  explanation,
  onDiscussExplanation,
  onContinueCourse,
  onUnitAction,
  explanationTurns,
  courseMaterials,
  onSaveExplanationToLibrary,
  explanationOwnerId,
  onCaptureResponse,
  sourceMessageId,
  onSaveExerciseToLibrary,
  onSaveSessionToLibrary,
  sessionSavedToLibrary,
  savingSessionToLibrary,
  contextOpen,
  onToggleContext,
  contextToggleRef,
}: ChatPanelProps) {
  const scrollAreaId = useId()
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const didInitialScrollRef = useRef(false)
  const isNearBottomRef = useRef(true)
  const captureSelection = useRef("")
  const [showScrollToBottom, setShowScrollToBottom] = useState(false)
  const activeExerciseIsInHistory = !messagesLoading && exercise && messages.some((message) => {
    const metadata = (message as UIMessage & { metadata?: Record<string, unknown> }).metadata
    return (metadata?.exercise as PublicExercise | undefined)?.id === exercise.id
  })
  const courseMessages = new Map<string, string>()
  for (const message of messages) {
    const metadata = message.metadata as { persisted?: boolean; explanation?: ExplanationPayload } | undefined
    const requestId = !isEducationalDocument(metadata?.explanation) ? metadata?.explanation?.course_progress?.request_id : undefined
    if (metadata?.persisted && requestId) courseMessages.set(requestId, message.id)
  }
  const latestByDocument = useMemo(() => {
    const result = new Map<string, string>()
    for (const [request, turn] of explanationTurns ?? []) {
      const source = turn.saved?.course_progress?.document_id
      if (source && !turn.saved?.historical_source) result.set(source, request)
    }
    return result
  }, [explanationTurns])
  const last = messages.at(-1)
  const active = (status === "streaming" || status === "submitted") && last?.role === "assistant"
    ? last.metadata as { request_id?: string; unitActionFrom?: string } | undefined : undefined
  const activeTurn = active?.request_id ? explanationTurns?.get(active.request_id) : undefined
  const attachedRun = active?.unitActionFrom ? explanationTurns?.get(active.unitActionFrom) : undefined
  const superseded = useMemo(() => {
    const prior = new Set<string>()
    for (const [id, turn] of explanationTurns ?? []) {
      const card = turn.saved
      if (!card) continue
      if (supportedUnitActions(card).some((action) => {
        const child = explanationTurns?.get(action.request_id)?.saved
        return child && !child.historical_source && child.course_progress?.document_id === card.course_progress?.document_id
          && child.course_progress?.index_generation === card.course_progress?.index_generation
          && child.course_progress?.source_hash === card.course_progress?.source_hash
      })) prior.add(id)
    }
    return prior
  }, [explanationTurns])
  const usedUnitRequests = new Set(courseMessages.keys())

  useEffect(() => {
    const viewport = scrollAreaRef.current
    if (!viewport) return
    const updateScrollButton = () => {
      const distanceToBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight
      isNearBottomRef.current = distanceToBottom <= 160
      setShowScrollToBottom(distanceToBottom > 160)
    }
    updateScrollButton()
    viewport.addEventListener("scroll", updateScrollButton, { passive: true })
    const resizeObserver = new ResizeObserver(() => {
      if (didInitialScrollRef.current && isNearBottomRef.current) viewport.scrollTop = viewport.scrollHeight
      updateScrollButton()
    })
    resizeObserver.observe(viewport)
    if (viewport.firstElementChild) resizeObserver.observe(viewport.firstElementChild)
    return () => {
      viewport.removeEventListener("scroll", updateScrollButton)
      resizeObserver.disconnect()
    }
  }, [messagesLoading])

  const scrollToBottom = () => {
    const viewport = scrollAreaRef.current
    if (!viewport) return
    viewport.focus({ preventScroll: true })
    viewport.scrollTo({ top: viewport.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" })
    isNearBottomRef.current = true
  }

  useLayoutEffect(() => {
    if (messagesLoading) {
      didInitialScrollRef.current = false
      return
    }
    if (didInitialScrollRef.current && !isNearBottomRef.current) return

    const frame = requestAnimationFrame(() => {
      const viewport = scrollAreaRef.current
      if (!viewport) return
      if (!didInitialScrollRef.current && sourceMessageId) {
        const source = document.getElementById(`message-${sourceMessageId}`)
        if (source) {
          viewport.scrollTop += source.getBoundingClientRect().top - viewport.getBoundingClientRect().top
          didInitialScrollRef.current = true
          isNearBottomRef.current = false
          return
        }
      }
      viewport.scrollTop = viewport.scrollHeight
      didInitialScrollRef.current = true
      isNearBottomRef.current = true
    })
    return () => cancelAnimationFrame(frame)
  }, [messagesLoading, messages, status, exercise?.id, correction?.attempt_id, explanation, sourceMessageId])

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {/* Chat Header */}
      <div className="flex shrink-0 flex-col gap-3 border-b border-border/40 px-4 py-3 sm:px-6 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <h2 className="min-w-0 flex-1 truncate font-serif text-lg font-medium italic">
            {learningMode === "socratic" ? "Socratic Dialogue" : learningMode === "exercise" ? "Practice Exercises" : "Explain a Topic"}: {sessionTitle}
          </h2>
          <Badge
            variant="outline"
            className="shrink-0 border-secondary/30 bg-secondary/10 text-secondary text-[10px] uppercase tracking-wider"
          >
            <span role="status">{connection ?? "Active session"}</span>
          </Badge>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2 xl:shrink-0 xl:justify-end">
          <Select value={language} onValueChange={(value) => onLanguageChange(value as "fr" | "en")}>
            <SelectTrigger className="w-28 max-w-full" aria-label="Response language"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="fr">Français</SelectItem><SelectItem value="en">English</SelectItem></SelectContent>
          </Select>
          <Select value={learningMode} onValueChange={(value) => onLearningModeChange(value as LearningMode)}>
            <SelectTrigger className="w-44 max-w-full" aria-label="Learning mode">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="socratic">Socratic dialogue</SelectItem>
              <SelectItem value="exercise">Practice exercises</SelectItem>
              <SelectItem value="explain">Explain a topic</SelectItem>
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 px-2 text-muted-foreground hover:text-secondary"
            aria-label={sessionSavedToLibrary ? "Saved to Library" : "Save inquiry to Library"}
            title={sessionSavedToLibrary ? "Saved to Library" : "Save inquiry to Library"}
            disabled={sessionSavedToLibrary || savingSessionToLibrary || messagesLoading || messages.length === 0}
            onClick={onSaveSessionToLibrary}
          >
            <Bookmark className={`h-4 w-4 ${sessionSavedToLibrary ? "fill-current text-secondary" : ""}`} />
            <span>{savingSessionToLibrary ? "Saving…" : sessionSavedToLibrary ? "Saved" : "Save"}</span>
          </Button>
          <Button type="button" variant="outline" size="icon" className="h-8 w-8 shrink-0" ref={contextToggleRef} onClick={onToggleContext} aria-expanded={contextOpen} aria-controls="inquiry-context" aria-label={contextOpen ? "Hide course context" : "Show course context"} title={contextOpen ? "Hide course context" : "Show course context"}>
            {contextOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollAreaRef} id={scrollAreaId} role="region" aria-label="Chat messages" tabIndex={0}
        className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-y-contain focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring">
        <div className="flex w-full min-w-0 max-w-full flex-col overflow-x-hidden pb-2">
          <MessageList
            messages={messages}
            isLoading={messagesLoading}
            status={status}
            progress={progress}
            renderAfterMessage={(message) => {
              const metadata = (message as UIMessage & { metadata?: Record<string, unknown> }).metadata
              const turn = typeof metadata?.request_id === "string" ? explanationTurns?.get(metadata.request_id) : undefined
              if (message.role !== "assistant") return turn && !turn.messageId && !turn.saved
                ? <LiveExplanation turn={turn} french={language === "fr"} /> : null
              const messageExercise = metadata?.exercise as PublicExercise | undefined
              const messageCorrection = metadata?.correction as PublicCorrection | undefined
              const messageExplanation = metadata?.explanation as ExplanationPayload | undefined
              const courseProgress = isEducationalDocument(messageExplanation) ? undefined : messageExplanation?.course_progress
              const request = courseProgress?.request_id
              const structured = request ? explanationTurns?.get(request)?.saved : undefined
              const documentId = structured?.course_progress?.document_id
              const material = documentId ? courseMaterials?.find((item) => item.documentId === documentId) : undefined
              const previous = []
              if (documentId && request === latestByDocument.get(documentId)) {
                for (const [earlierRequest, turn] of explanationTurns ?? []) {
                  if (earlierRequest === request) break
                  if (!turn.saved?.historical_source) previous.push(...turn.stream.versions)
                }
              }
              const previousParts = courseProgress?.generated_parts?.flatMap(({ part, request_id }) => {
                const messageId = request_id && courseMessages.get(request_id)
                return messageId && part !== courseProgress.part ? [{ part, messageId }] : []
              })
              const canCapture = !metadata?.partial && !messageExercise && metadata?.persisted === true &&
                (status === "ready" || status === "error" || message.id !== messages.at(-1)?.id)
              const selectedText = () => {
                const selection = window.getSelection()
                const wrapper = document.getElementById(`message-${message.id}`)
                return selection && wrapper?.contains(selection.anchorNode) && wrapper.contains(selection.focusNode)
                  ? selection.toString().trim() : ""
              }
              const captureAction = canCapture ? {
                onPointerDown: () => { captureSelection.current = selectedText() },
                onClick: (event: MouseEvent<HTMLButtonElement>) => {
                  onCaptureResponse({ messageId: message.id, title: (isEducationalDocument(messageExplanation)
                    ? messageExplanation.title : messageExplanation?.sections?.[0]?.heading) ||
                    (messageCorrection ? "Exercise feedback" : sessionTitle), selection: (event.detail ? captureSelection.current : "") || selectedText() })
                  captureSelection.current = ""
                },
              } : undefined
              const card = messageExplanation && <ExplanationCard explanation={messageExplanation} ownerId={explanationOwnerId}
                    explanationId={metadata?.persisted === true ? message.id : undefined}
                    onDiscuss={onDiscussExplanation}
                    onContinueCourse={metadata?.persisted && courseProgress?.next_request_id &&
                      !courseMessages.has(courseProgress.next_request_id) ? onContinueCourse : undefined}
                    onUnitAction={metadata?.persisted === true && documentId &&
                      request === latestByDocument.get(documentId) ? onUnitAction : undefined}
                    usedUnitRequests={usedUnitRequests}
                    unitContext={structured ? { previous, turn, live: request === active?.unitActionFrom ? activeTurn : undefined,
                      source: material ? { title: material.summary?.title || material.filename } : undefined } : undefined}
                    coursePartLinks={previousParts}
                    onSaveToLibrary={metadata?.persisted ? (value) => onSaveExplanationToLibrary(value, message.id) : undefined}
                    notebookCapture={captureAction} disabled={status !== "ready" && status !== "error"} />
              return (
                <div className="flex w-full min-w-0 max-w-full flex-col gap-4">
                  {messageExercise && <ExerciseCard key={messageExercise.id} exercise={messageExercise} onNextExercise={onNextExercise} onSubmitAttempt={onSubmitAttempt} disabled={status !== "ready"} submissionLocked={solution?.exercise_id === messageExercise.id} />}
                  {messageCorrection && <ExerciseFeedbackCard correction={messageCorrection} solution={solution} onRevealSolution={onRevealSolution} onNextExercise={onNextExercise} onSaveToLibrary={onSaveExerciseToLibrary} disabled={status !== "ready"} />}
                  {request && superseded.has(request) ? <details className="min-w-0">
                    <summary className="min-h-11 cursor-pointer py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring">
                      {language === "fr" ? "Explication précédente" : "Earlier explanation"}
                    </summary>{card}
                  </details> : card}
                  {!messageExplanation && turn && !(turn === activeTurn && attachedRun?.saved && attachedRun.messageId) &&
                    <LiveExplanation turn={turn} french={language === "fr"} />}
                  {!messageExplanation && captureAction && <Button type="button" variant="ghost" size="sm"
                    className="self-start text-muted-foreground" {...captureAction}><NotebookPen />Save to Notebook</Button>}
                </div>
              )
            }}
          />
          {exercise && !activeExerciseIsInHistory && (
            <div className="flex w-full min-w-0 max-w-full flex-col gap-4">
              <ExerciseCard
                key={exercise.id}
                exercise={exercise}
                onNextExercise={onNextExercise}
                onSubmitAttempt={onSubmitAttempt}
                disabled={status !== "ready"}
                submissionLocked={solution?.exercise_id === exercise.id}
              />
            </div>
          )}
        </div>
      </div>
      {/* Error retry bar */}
      {status === "error" && error && (
        <div className="flex items-center justify-center gap-3 border-t border-destructive/20 bg-destructive/5 px-4 py-2.5">
          <p role="alert" className="text-xs text-destructive">{error.message}</p>
          {onRetry && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 text-xs border-destructive/30 text-destructive hover:bg-destructive/10"
              onClick={onRetry}
            >
              <RotateCcw className="h-3 w-3" />
              Retry
            </Button>
          )}
        </div>
      )}

      {(status === "submitted" || status === "streaming") && (
        <div className="flex items-center justify-between gap-2 px-4 py-2">
          <span role="status" className="text-xs text-muted-foreground">{progress || "Generating response…"}</span>
          <Button type="button" variant="outline" size="sm" onClick={onStop}>Stop</Button>
        </div>
      )}
      {status === "ready" && !messagesLoading && canRegenerate && onRetry && (
        <div className="flex items-center justify-end gap-2 px-4 py-1">
          {progress && <span role="status" className="text-xs text-muted-foreground">{progress}</span>}
          <Button type="button" variant="ghost" size="sm" onClick={onRetry}>{progress ? "Retry" : "Regenerate"}</Button>
        </div>
      )}
      {/* Input */}
      {showScrollToBottom && !messagesLoading && <div className="flex shrink-0 justify-center px-4 py-1">
        <Button type="button" variant="secondary" size="icon" aria-controls={scrollAreaId}
          aria-label="Scroll to latest message" title="Scroll to latest message"
          className="size-8 rounded-full border border-border shadow-lg" onClick={scrollToBottom}>
          <ArrowDown className="h-4 w-4" aria-hidden />
        </Button>
      </div>}
      <ChatInput
        value={input}
        onChange={onInputChange}
        onSubmit={onSubmit}
        isDisabled={messagesLoading || (status !== "ready" && status !== "error")}
        onAttach={onAttach}
      />
    </div>
  )
}
