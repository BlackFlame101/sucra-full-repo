"use client"

import { useSyncExternalStore } from "react"
import type { UnitOutput } from "@/lib/explanation-v2"

export interface UnitActivityScope {
  ownerId?: string
  documentId?: string
  generation?: number
  sourceHash?: string
}

export function unitActivityKey(scope: UnitActivityScope | undefined, unit: Pick<UnitOutput, "logical_id" | "content_version">, item: string) {
  if (!scope?.ownerId || !scope.documentId || scope.generation === undefined || !scope.sourceHash ||
    !unit.logical_id || !unit.content_version || !item) return ""
  return "socra:unit-activity:v1:" + JSON.stringify([scope.ownerId, scope.documentId, scope.generation, scope.sourceHash,
    unit.logical_id, unit.content_version, item])
}

export function requirementActivityId(blockId: string, text: string) {
  // Preserve a mark when the same sourced block is reused. A rewritten requirement gets a new key.
  let hash = 2166136261
  for (const char of text) hash = Math.imul(hash ^ (char.codePointAt(0) ?? 0), 16777619)
  return blockId + ":" + (hash >>> 0).toString(36)
}

const eventName = "socra:unit-activity"
function subscribe(update: () => void) {
  window.addEventListener("storage", update)
  window.addEventListener(eventName, update)
  return () => {
    window.removeEventListener("storage", update)
    window.removeEventListener(eventName, update)
  }
}

export function UnitActivityToggle({ storageKey, label }: { storageKey: string; label: string }) {
  const checked = useSyncExternalStore(subscribe, () => {
    try { return Boolean(storageKey && localStorage.getItem(storageKey) === "1") }
    catch { return false }
  }, () => false)
  if (!storageKey) return null
  return <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 text-xs text-muted-foreground">
    <input type="checkbox" checked={checked} className="size-4 shrink-0 accent-primary focus-visible:outline-2 focus-visible:outline-ring"
      onChange={(event) => {
        try {
          if (event.currentTarget.checked) localStorage.setItem(storageKey, "1")
          else localStorage.removeItem(storageKey)
          window.dispatchEvent(new Event(eventName))
        } catch { /* Storage is optional. */ }
      }} />
    {label}
  </label>
}
