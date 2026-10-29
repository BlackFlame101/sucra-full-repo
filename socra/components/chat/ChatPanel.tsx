"use client"

import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { Share2, MoreVertical, RotateCcw, ArrowDown } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
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
  messagesLoading: boolean
  error?: Error | null
  onInputChange: (value: string) => void
  onSubmit: () => void
  onRetry?: () => void
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
}

export function ChatPanel({
  sessionTitle,
  language,
  onLanguageChange,
  messages,
  input,
  status,
  messagesLoading,
  error,
  onInputChange,
  onSubmit,
  onRetry,
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
}: ChatPanelProps) {
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const didInitialScrollRef = useRef(false)
  const isNearBottomRef = useRef(true)
  const [showScrollToBottom, setShowScrollToBottom] = useState(false)
  const activeExerciseIsInHistory = !messagesLoading && exercise && messages.some((message) => {
    const metadata = (message as UIMessage & { metadata?: Record<string, unknown> }).metadata
    return (metadata?.exercise as PublicExercise | undefined)?.id === exercise.id
  })

  useEffect(() => {
    const viewport = scrollAreaRef.current?.querySelector<HTMLElement>(
      '[data-slot="scroll-area-viewport"]'
    )
    if (!viewport) return
    const updateScrollButton = () => {
      const distanceToBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight
      isNearBottomRef.current = distanceToBottom <= 160
      setShowScrollToBottom(distanceToBottom > 160)
    }
    updateScrollButton()
    viewport.addEventListener("scroll", updateScrollButton, { passive: true })
    const resizeObserver = new ResizeObserver(updateScrollButton)
    resizeObserver.observe(viewport)
    if (viewport.firstElementChild) resizeObserver.observe(viewport.firstElementChild)
    return () => {
      viewport.removeEventListener("scroll", updateScrollButton)
      resizeObserver.disconnect()
    }
  }, [messagesLoading])

  const scrollToBottom = () => {
    const viewport = scrollAreaRef.current?.querySelector<HTMLElement>(
      '[data-slot="scroll-area-viewport"]'
    )
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
      const viewport = scrollAreaRef.current?.querySelector<HTMLElement>(
        '[data-slot="scroll-area-viewport"]'
      )
      if (!viewport) return
      viewport.scrollTop = viewport.scrollHeight
      didInitialScrollRef.current = true
      isNearBottomRef.current = true
    })
    return () => cancelAnimationFrame(frame)
  }, [messagesLoading, messages, status, exercise?.id, correction?.attempt_id, explanation?.check_question])

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Chat Header */}
      <div className="flex items-center justify-between border-b border-border/40 px-4 sm:px-6 py-3">
        <div className="flex items-center gap-3 min-w-0">
          <h2 className="font-serif text-lg font-medium italic truncate">
            {learningMode === "socratic" ? "Socratic Dialogue" : learningMode === "exercise" ? "Practice Exercises" : "Explain a Topic"}: {sessionTitle}
          </h2>
          <Badge
            variant="outline"
            className="shrink-0 border-secondary/30 bg-secondary/10 text-secondary text-[10px] uppercase tracking-wider"
          >
            Active Session
          </Badge>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Select value={language} onValueChange={(value) => onLanguageChange(value as "fr" | "en")}>
            <SelectTrigger className="w-28" aria-label="Response language"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="fr">Français</SelectItem><SelectItem value="en">English</SelectItem></SelectContent>
          </Select>
          <Select value={learningMode} onValueChange={(value) => onLearningModeChange(value as LearningMode)}>
            <SelectTrigger className="w-44" aria-label="Learning mode">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="socratic">Socratic dialogue</SelectItem>
              <SelectItem value="exercise">Practice exercises</SelectItem>
              <SelectItem value="explain">Explain a topic</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground">
            <Share2 className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground">
            <MoreVertical className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Messages */}
      <ScrollArea ref={scrollAreaRef} className="flex-1 min-h-0">
        <div className="flex flex-col pb-2">
          <MessageList
            messages={messages}
            isLoading={messagesLoading}
            status={status}
            renderAfterMessage={(message) => {
              if (message.role !== "assistant") return null
              const metadata = (message as UIMessage & { metadata?: Record<string, unknown> }).metadata
              const messageExercise = metadata?.exercise as PublicExercise | undefined
              const messageCorrection = metadata?.correction as PublicCorrection | undefined
              const messageExplanation = metadata?.explanation as PublicExplanation | undefined
              return (
                <div className="flex flex-col gap-4">
                  {messageExercise && <ExerciseCard key={messageExercise.id} exercise={messageExercise} onNextExercise={onNextExercise} onSubmitAttempt={onSubmitAttempt} disabled={status !== "ready"} submissionLocked={solution?.exercise_id === messageExercise.id} />}
                  {messageCorrection && <ExerciseFeedbackCard correction={messageCorrection} solution={solution} onRevealSolution={onRevealSolution} onNextExercise={onNextExercise} disabled={status !== "ready"} />}
                  {messageExplanation && <ExplanationCard explanation={messageExplanation} onDiscuss={onDiscussExplanation} disabled={status !== "ready"} />}
                </div>
              )
            }}
          />
          {exercise && !activeExerciseIsInHistory && (
            <div className="flex flex-col gap-4">
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
      </ScrollArea>
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
          <p className="text-xs text-destructive">Something went wrong.</p>
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

      {/* Input */}
      <ChatInput
        value={input}
        onChange={onInputChange}
        onSubmit={onSubmit}
        isDisabled={status !== "ready" && status !== "error"}
        onAttach={onAttach}
      />
    </div>
  )
}
