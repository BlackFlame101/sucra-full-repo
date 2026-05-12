"use client"

import { ScrollArea } from "@/components/ui/scroll-area"
import { KeyTerms } from "./KeyTerms"
import { SuggestedReading } from "./SuggestedReading"

interface Reading {
  documentName: string
  pageNumber: number
  section: string
  chapter?: string
}

interface ContextPanelProps {
  keyTerms: string[]
  suggestedReadings: Reading[]
  isLoading?: boolean
}

export function ContextPanel({
  keyTerms,
  suggestedReadings,
  isLoading,
}: ContextPanelProps) {
  return (
    <div className="flex h-full w-full min-w-0 flex-col overflow-hidden border-l border-border/40 bg-card/20">
      {/* Header */}
      <div className="border-b border-border/40 px-4 py-3 shrink-0">
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          Dialectic Context
        </h2>
      </div>

      {/* Content */}
      <ScrollArea className="flex-1 min-w-0 overflow-hidden">
        <div className="space-y-6 p-4 min-w-0 max-w-full">
          <KeyTerms terms={keyTerms} isLoading={isLoading} />
          <SuggestedReading readings={suggestedReadings} isLoading={isLoading} />
        </div>
      </ScrollArea>
    </div>
  )
}
