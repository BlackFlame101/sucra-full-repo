"use client"

import { BookOpen } from "lucide-react"

interface Reading {
  documentName: string
  pageNumber: number
  section: string
  chapter?: string
}

interface SuggestedReadingProps {
  readings: Reading[]
  isLoading?: boolean
}

export function SuggestedReading({ readings, isLoading }: SuggestedReadingProps) {
  return (
    <div className="min-w-0 overflow-hidden">
      <h3 className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-3">
        Suggested Reading
      </h3>
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <div
              key={i}
              className="rounded-xl border border-border/50 bg-card/50 p-3 space-y-2"
            >
              <div className="h-4 w-3/4 rounded bg-muted animate-pulse" />
              <div className="h-3 w-1/2 rounded bg-muted animate-pulse" />
            </div>
          ))}
        </div>
      ) : readings.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">
          Reading suggestions will appear based on your discussion
        </p>
      ) : (
        <div className="w-full min-w-0 space-y-3">
          {readings.map((reading, i) => (
            <div
              key={i}
              className="box-border w-full min-w-0 overflow-hidden rounded-xl border border-border/50 bg-card/50 p-3 hover:bg-card/70 transition-colors"
            >
              <div className="flex w-full min-w-0 items-start gap-2.5">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-secondary/10 mt-0.5">
                  <BookOpen className="h-3.5 w-3.5 text-secondary" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex w-full min-w-0 items-center justify-between gap-2">
                    <p className="min-w-0 truncate text-sm font-medium" title={reading.section}>{reading.section}</p>
                    {reading.chapter && (
                      <span className="text-[10px] uppercase tracking-wider text-muted-foreground shrink-0">
                        {reading.chapter}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 max-w-full truncate text-xs text-muted-foreground" title={reading.documentName}>
                    {reading.documentName}
                    {reading.pageNumber ? ` \u00B7 Page ${reading.pageNumber}` : ""}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
