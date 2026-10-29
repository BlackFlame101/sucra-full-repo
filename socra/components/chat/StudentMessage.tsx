"use client"

interface StudentMessageProps {
  content: string
}

export function StudentMessage({ content }: StudentMessageProps) {
  return (
    <div className="flex w-full min-w-0 flex-col items-end">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-1 mr-1">
        You
      </span>
      <div className="min-w-0 max-w-[80%] rounded-xl rounded-tr-sm border border-secondary/20 bg-secondary/10 px-4 py-3">
        <p className="break-words text-sm leading-relaxed">{content}</p>
      </div>
    </div>
  )
}
