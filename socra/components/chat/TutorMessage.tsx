"use client"

import { Bot } from "lucide-react"

interface TutorMessageProps {
  content: string
  isStreaming?: boolean
  partial?: boolean
}

function inlineMarkdown(text: string) {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1) return <code key={index} className="rounded bg-muted px-1 font-mono text-sm">{part.slice(1, -1)}</code>
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={index}>{part.slice(1, -1)}</em>
    return part
  })
}

function formatTutorContent(content: string) {
  return content.split(/^```[^\n]*\n?/m).map((block, index) => {
    if (index % 2 === 1) {
      return <pre key={index} className="my-2 overflow-x-auto rounded bg-muted p-3 text-sm"><code>{block.trimEnd()}</code></pre>
    }
    return <div key={index} className="whitespace-pre-wrap break-words">
      {block.split("\n").map((line, lineIndex) => {
        const heading = /^#{1,6}\s+(.+)$/.exec(line)
        if (heading) return <p key={lineIndex} className="font-semibold">{inlineMarkdown(heading[1])}</p>
        return <div key={lineIndex}>{line ? inlineMarkdown(line) : <br />}</div>
      })}
    </div>
  })
}

export function TutorMessage({ content, isStreaming, partial }: TutorMessageProps) {
  return (
    <div className="flex min-w-0 max-w-[85%] gap-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary/15 mt-1">
        <Bot className="h-4 w-4 text-secondary" />
      </div>
      <div className="space-y-1 min-w-0">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground inline-flex items-center gap-1.5">
          Socra Tutor
          {isStreaming && (
            <span className="inline-flex items-center gap-1 text-secondary/80 normal-case tracking-normal">
              <span className="h-1 w-1 rounded-full bg-secondary animate-pulse" />
              <span className="text-[10px] font-normal">Responding</span>
            </span>
          )}
        </span>
        <div className="min-w-0 max-w-full rounded-xl rounded-tl-sm border border-border/50 bg-card/50 px-4 py-3">
          <div className="font-serif text-[15px] leading-relaxed text-foreground/90">
            {formatTutorContent(content)}
            {partial && <p className="mt-2 text-xs text-muted-foreground">Partial response</p>}
            {!isStreaming && !partial && <button type="button" className="mt-2 text-xs text-secondary" onClick={() => void navigator.clipboard.writeText(content)}>Copy response</button>}
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
