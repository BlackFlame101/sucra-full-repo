"use client"

import { Badge } from "@/components/ui/badge"

interface KeyTermsProps {
  terms: string[]
  isLoading?: boolean
}

export function KeyTerms({ terms, isLoading }: KeyTermsProps) {
  return (
    <div className="min-w-0 overflow-hidden">
      <h3 className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-3">
        Key Terms Identified
      </h3>
      {isLoading ? (
        <div className="flex flex-wrap gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-6 w-20 rounded-full bg-muted animate-pulse"
            />
          ))}
        </div>
      ) : terms.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">
          Key terms will appear as the conversation progresses
        </p>
      ) : (
        <div className="flex flex-wrap gap-2 min-w-0 overflow-hidden">
          {terms.map((term) => (
            <Badge
              key={term}
              variant="outline"
              className="border-border/60 bg-muted/40 text-foreground/80 text-xs font-normal truncate max-w-[140px]"
            >
              {term}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}
