"use client"

interface StudentMessageProps {
  content: string
}

export function StudentMessage({ content }: StudentMessageProps) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-1 mr-1">
        You
      </span>
      <div className="max-w-[80%] rounded-xl rounded-tr-sm border border-secondary/20 bg-secondary/10 px-4 py-3">
        <p className="text-sm leading-relaxed">{content}</p>
      </div>
    </div>
  )
}
