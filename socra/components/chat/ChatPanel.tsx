"use client"

import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { Bookmark, MoreVertical, NotebookPen, RotateCcw, ArrowDown, PanelRightClose, PanelRightOpen } from "lucide-react"
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
import type { LearningMode, PublicCorrection, PublicExercise, PublicExplanation, PublicSolution } from "@/lib/socra-ws"
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
  explanation: PublicExplanation | null
  onDiscussExplanation: (question: string) => void
  onSaveExplanationToLibrary: (explanation: PublicExplanation) => void
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
  onSaveExplanationToLibrary,
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
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const didInitialScrollRef = useRef(false)
  const isNearBottomRef = useRef(true)
  const captureSelection = useRef("")
  const [showScrollToBottom, setShowScrollToBottom] = useState(false)
  const activeExerciseIsInHistory = !messagesLoading && exercise && messages.some((message) => {
    const metadata = (message as UIMessage & { metadata?: Record<string, unknown> }).metadata
    return (metadata?.exercise as PublicExercise | undefined)?.id === exercise.id
  })

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
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" })
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
  }, [messagesLoading, messages, status, exercise?.id, correction?.attempt_id, explanation?.check_question, sourceMessageId])

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
          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground">
            <MoreVertical className="h-4 w-4" />
          </Button>
          <Button type="button" variant="outline" size="icon" className="h-8 w-8 shrink-0" ref={contextToggleRef} onClick={onToggleContext} aria-expanded={contextOpen} aria-controls="inquiry-context" aria-label={contextOpen ? "Hide course context" : "Show course context"} title={contextOpen ? "Hide course context" : "Show course context"}>
            {contextOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollAreaRef} className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-y-contain">
        <div className="flex w-full min-w-0 max-w-full flex-col overflow-x-hidden pb-2">
          <MessageList
            messages={messages}
            isLoading={messagesLoading}
            status={status}
            progress={progress}
            renderAfterMessage={(message) => {
              if (message.role !== "assistant") return null
              const metadata = (message as UIMessage & { metadata?: Record<string, unknown> }).metadata
              const messageExercise = metadata?.exercise as PublicExercise | undefined
              const messageCorrection = metadata?.correction as PublicCorrection | undefined
              const messageExplanation = metadata?.explanation as PublicExplanation | undefined
              const canCapture = !metadata?.partial && !messageExercise && metadata?.persisted === true &&
                (status === "ready" || status === "error" || message.id !== messages.at(-1)?.id)
              const selectedText = () => {
                const selection = window.getSelection()
                const wrapper = document.getElementById(`message-${message.id}`)
                return selection && wrapper?.contains(selection.anchorNode) && wrapper.contains(selection.focusNode)
                  ? selection.toString().trim() : ""
              }
              return (
                <div className="flex w-full min-w-0 max-w-full flex-col gap-4">
                  {messageExercise && <ExerciseCard key={messageExercise.id} exercise={messageExercise} onNextExercise={onNextExercise} onSubmitAttempt={onSubmitAttempt} disabled={status !== "ready"} submissionLocked={solution?.exercise_id === messageExercise.id} />}
                  {messageCorrection && <ExerciseFeedbackCard correction={messageCorrection} solution={solution} onRevealSolution={onRevealSolution} onNextExercise={onNextExercise} onSaveToLibrary={onSaveExerciseToLibrary} disabled={status !== "ready"} />}
                  {messageExplanation && <ExplanationCard explanation={messageExplanation} onDiscuss={onDiscussExplanation} onSaveToLibrary={onSaveExplanationToLibrary} disabled={status !== "ready"} />}
                  {canCapture && <Button type="button" variant="ghost" size="sm" className="self-start text-muted-foreground"
                    onPointerDown={() => { captureSelection.current = selectedText() }}
                    onClick={(event) => {
                      onCaptureResponse({ messageId: message.id, title: messageExplanation?.sections?.[0]?.heading ||
                        (messageCorrection ? "Exercise feedback" : sessionTitle), selection: (event.detail ? captureSelection.current : "") || selectedText() })
                      captureSelection.current = ""
                    }}><NotebookPen />Save to Notebook</Button>}
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
      {showScrollToBottom && (
        <Button
          type="button"
          variant="secondary"
          size="icon"
          aria-label="Scroll to latest message"
          title="Scroll to latest message"
          className="absolute bottom-24 left-1/2 z-20 -translate-x-1/2 rounded-full border border-border shadow-lg"
          onClick={scrollToBottom}
        >
          <ArrowDown className="h-4 w-4" />
        </Button>
      )}

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
