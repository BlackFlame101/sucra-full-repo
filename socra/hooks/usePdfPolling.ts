"use client"

import { useEffect } from "react"

const delays = [2_000, 2_000, 3_000, 4_000, 8_000, 15_000, 30_000]

export function usePdfPolling(active: boolean, refresh: (signal: AbortSignal) => Promise<boolean | void>) {
  useEffect(() => {
    if (!active) return

    const controller = new AbortController()
    let timer: number | undefined
    let delayIndex = 0
    let running = false
    let finished = false

    function schedule() {
      if (controller.signal.aborted || finished || document.hidden) return
      timer = window.setTimeout(poll, delays[delayIndex])
      delayIndex = Math.min(delayIndex + 1, delays.length - 1)
    }

    async function poll() {
      if (running || finished || controller.signal.aborted || document.hidden) return
      running = true
      try {
        finished = await refresh(controller.signal) === false
      } catch {
        // A transient error leaves the last known state visible.
      } finally {
        running = false
        schedule()
      }
    }

    function handleVisibility() {
      window.clearTimeout(timer)
      if (!document.hidden) {
        delayIndex = 0
        void poll()
      }
    }

    document.addEventListener("visibilitychange", handleVisibility)
    schedule()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
      document.removeEventListener("visibilitychange", handleVisibility)
    }
  }, [active, refresh])
}
