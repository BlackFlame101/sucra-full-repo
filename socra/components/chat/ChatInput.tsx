"use client"

import { useRef, useEffect, type KeyboardEvent } from "react"
import { ArrowUp, Paperclip, Mic } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface ChatInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  isDisabled?: boolean
  onAttach?: () => void
}

export function ChatInput({ value, onChange, onSubmit, isDisabled, onAttach }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() && !isDisabled) {
        onSubmit()
      }
    }
  }

  const adjustHeight = () => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = "auto"
      textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`
    }
  }

  useEffect(() => {
    if (!value) {
      const textarea = textareaRef.current
      if (textarea) {
        textarea.style.height = "auto"
      }
    }
  }, [value])

  return (
    <div className="border-t border-border/40 bg-background/80 backdrop-blur-sm px-3 sm:px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-xl border border-border/50 bg-card/50 px-3 py-2 focus-within:border-secondary/40 transition-colors">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
                onClick={onAttach}
                disabled={!onAttach}
              >
                <Paperclip className="h-4 w-4" />
                <span className="sr-only">Upload PDF</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>Upload PDF</TooltipContent>
          </Tooltip>

          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => {
              onChange(e.target.value)
              adjustHeight()
            }}
            onKeyDown={handleKeyDown}
            placeholder="Ask your tutor..."
            disabled={isDisabled}
            rows={1}
            className="flex-1 resize-none bg-transparent py-1.5 text-sm outline-none placeholder:text-muted-foreground/60 disabled:opacity-50 max-h-40"
          />

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
                disabled
              >
                <Mic className="h-4 w-4" />
                <span className="sr-only">Voice input</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>Coming soon</TooltipContent>
          </Tooltip>

          <Button
            type="button"
            size="icon"
            className="h-8 w-8 shrink-0 rounded-lg bg-tertiary hover:bg-tertiary/80 text-tertiary-foreground"
            disabled={isDisabled || !value.trim()}
            onClick={() => {
              if (value.trim() && !isDisabled) onSubmit()
            }}
          >
            <ArrowUp className="h-4 w-4" />
            <span className="sr-only">Send message</span>
          </Button>
        </div>
      </div>
      <p className="text-center text-[10px] uppercase tracking-widest text-muted-foreground/50 mt-2">
        Socra encourages inquiry-based learning. Direct answers are rarely given.
      </p>
    </div>
  )
}
