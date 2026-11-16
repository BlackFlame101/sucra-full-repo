export function explanationProgressKey(ownerId?: string, explanationId?: string) {
  return ownerId && explanationId ? "socra:explanation-progress:v1:" + JSON.stringify([ownerId, explanationId]) : ""
}

export function readExplanationProgress(key: string, taskCount: number): Record<number, boolean> {
  if (!key) return {}
  try {
    const stored: unknown = JSON.parse(window.localStorage.getItem(key) ?? "{}")
    if (!stored || typeof stored !== "object" || Array.isArray(stored)) return {}
    return Object.fromEntries(Object.entries(stored).filter(([index, checked]) =>
      /^(0|[1-9]\d*)$/.test(index) && Number(index) < taskCount && typeof checked === "boolean"))
  } catch {
    return {}
  }
}

export function writeExplanationProgress(key: string, progress: Record<number, boolean>) {
  if (!key) return
  try {
    window.localStorage.setItem(key, JSON.stringify(progress))
  } catch {
    // The card remains usable when storage is disabled or full.
  }
}
