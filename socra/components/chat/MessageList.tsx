"use client"

import type { ReactNode } from "react"
import { Message } from "./Message"
import { Skeleton } from "@/components/ui/skeleton"
import { Bot } from "lucide-react"
import type { UIMessage } from "ai"

interface MessageListProps {
  messages: UIMessage[]
  isLoading?: boolean
  status?: string
  renderAfterMessage?: (message: UIMessage) => ReactNode
}

function getMessageText(message: UIMessage): string {
  return message.parts
    .filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text)
    .join("")
}

function TypingIndicator() {
  return (
    <div className="flex gap-3 max-w-[85%]">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary/15 mt-1">
        <Bot className="h-4 w-4 text-secondary" />
      </div>
      <div className="space-y-1">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          Socra Tutor
        </span>
        <div className="rounded-xl rounded-tl-sm border border-border/50 bg-card/50 px-4 py-3">
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-secondary/60 animate-pulse" />
            <span className="h-1.5 w-1.5 rounded-full bg-secondary/60 animate-pulse [animation-delay:0.2s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-secondary/60 animate-pulse [animation-delay:0.4s]" />
          </div>
        </div>
      </div>
    </div>
  )
}

function MessageSkeleton() {
  return (
    <div className="space-y-6 p-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className={`flex ${i % 2 === 1 ? "justify-end" : "gap-3"}`}>
          {i % 2 === 0 && <Skeleton className="h-9 w-9 rounded-lg shrink-0" />}
          <div className={`space-y-2 ${i % 2 === 1 ? "items-end" : ""}`}>
            <Skeleton className="h-3 w-20" />
            <Skeleton className={`h-20 ${i % 2 === 1 ? "w-64" : "w-80"} rounded-xl`} />
          </div>
        </div>
      ))}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-8">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-secondary/10 mb-6">
        <Bot className="h-8 w-8 text-secondary" />
      </div>
      <h3 className="font-serif text-xl font-medium mb-2">
        Begin Your Inquiry
      </h3>
      <p className="text-sm text-muted-foreground max-w-sm leading-relaxed">
        Ask a question about your course materials. Socra will guide you through
        Socratic dialogue — exploring ideas together rather than giving direct
        answers.
      </p>
    </div>
  )
}

export function MessageList({ messages, isLoading, status, renderAfterMessage }: MessageListProps) {
  if (isLoading) return <MessageSkeleton />
  if (messages.length === 0) return <EmptyState />

  // Show the typing-dots indicator whenever a turn is in flight AND we have
  // not yet received any visible assistant text. As soon as tokens start
  // streaming the per-message blinking caret in TutorMessage takes over.
  const last = messages[messages.length - 1]
  const lastIsEmptyAssistant =
    last?.role === "assistant" && getMessageText(last).length === 0
  const showTypingIndicator =
    status === "submitted" || (status === "streaming" && lastIsEmptyAssistant)

  return (
    <div className="flex flex-col gap-6 p-4 sm:p-6">
      {messages.map((message) => (
        <div key={message.id} className="contents">
          <Message
            message={message}
            isStreaming={
              status === "streaming" && message.id === last?.id && message.role === "assistant"
            }
          />
          {renderAfterMessage?.(message)}
        </div>
      ))}
      {showTypingIndicator && <TypingIndicator />}
    </div>
  )
}
