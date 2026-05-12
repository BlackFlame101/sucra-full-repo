"use client"

import { Share2, MoreVertical, RotateCcw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { MessageList } from "./MessageList"
import { ChatInput } from "./ChatInput"
import type { UIMessage } from "ai"

interface ChatPanelProps {
  sessionTitle: string
  messages: UIMessage[]
  input: string
  status: string
  messagesLoading: boolean
  error?: Error | null
  onInputChange: (value: string) => void
  onSubmit: () => void
  onRetry?: () => void
  onAttach?: () => void
}

export function ChatPanel({
  sessionTitle,
  messages,
  input,
  status,
  messagesLoading,
  error,
  onInputChange,
  onSubmit,
  onRetry,
  onAttach,
}: ChatPanelProps) {
  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Chat Header */}
      <div className="flex items-center justify-between border-b border-border/40 px-4 sm:px-6 py-3">
        <div className="flex items-center gap-3 min-w-0">
          <h2 className="font-serif text-lg font-medium italic truncate">
            Socratic Dialogue: {sessionTitle}
          </h2>
          <Badge
            variant="outline"
            className="shrink-0 border-secondary/30 bg-secondary/10 text-secondary text-[10px] uppercase tracking-wider"
          >
            Active Session
          </Badge>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground">
            <Share2 className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground">
            <MoreVertical className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Messages */}
      <ScrollArea className="flex-1 min-h-0">
        <MessageList
          messages={messages}
          isLoading={messagesLoading}
          status={status}
        />
      </ScrollArea>

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
