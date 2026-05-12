"use client"

import { Bot } from "lucide-react"

interface TutorMessageProps {
  content: string
  isStreaming?: boolean
}

function formatTutorContent(content: string) {
  return content.split("\n").map((line, i) => {
    if (!line.trim()) return <br key={i} />

    const parts: React.ReactNode[] = []
    const regex = /\*([^*]+)\*/g
    let lastIndex = 0
    let match

    while ((match = regex.exec(line)) !== null) {
      if (match.index > lastIndex) {
        parts.push(line.slice(lastIndex, match.index))
      }
      parts.push(
        <em key={`${i}-${match.index}`} className="font-serif italic text-secondary">
          {match[1]}
        </em>
      )
      lastIndex = regex.lastIndex
    }

    if (lastIndex < line.length) {
      parts.push(line.slice(lastIndex))
    }

    return (
      <p key={i} className="mb-2 last:mb-0">
        {parts.length > 0 ? parts : line}
      </p>
    )
  })
}

export function TutorMessage({ content, isStreaming }: TutorMessageProps) {
  return (
    <div className="flex gap-3 max-w-[85%]">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary/15 mt-1">
        <Bot className="h-4 w-4 text-secondary" />
      </div>
      <div className="space-y-1 min-w-0">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground inline-flex items-center gap-1.5">
          Socra Tutor
          {isStreaming && (
            <span className="inline-flex items-center gap-1 text-secondary/80 normal-case tracking-normal">
              <span className="h-1 w-1 rounded-full bg-secondary animate-pulse" />
              <span className="text-[10px] font-normal">thinking out loud…</span>
            </span>
          )}
        </span>
        <div className="rounded-xl rounded-tl-sm border border-border/50 bg-card/50 px-4 py-3">
          <div className="font-serif text-[15px] leading-relaxed text-foreground/90">
            {formatTutorContent(content)}
            {isStreaming && (
              <span
                aria-hidden
                className="inline-block w-[2px] h-4 ml-0.5 bg-secondary/70 align-middle animate-pulse"
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
