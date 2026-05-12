"use client"

import { useState, useCallback } from "react"
import type { Session, Message } from "@/types"

export function useSession(courseId: string) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [currentSession, setCurrentSession] = useState<Session | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)

  const fetchSessions = useCallback(async () => {
    const res = await fetch(`/api/sessions/${courseId}`)
    if (res.ok) {
      const data = await res.json()
      setSessions(data)
      return data as Session[]
    }
    return []
  }, [courseId])

  const createSession = useCallback(
    async (title = "New Inquiry") => {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ courseId, title }),
      })
      if (!res.ok) throw new Error("Failed to create session")
      const session = await res.json()
      setSessions((prev) => [session, ...prev])
      setCurrentSession(session)
      return session as Session
    },
    [courseId]
  )

  const loadSession = useCallback(async (sessionId: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/sessions/${sessionId}/messages`)
      if (res.ok) {
        const data = await res.json()
        setMessages(data)
        return data as Message[]
      }
      return []
    } finally {
      setLoading(false)
    }
  }, [])

  const updateSessionTitle = useCallback(
    async (sessionId: string, title: string) => {
      const res = await fetch(`/api/sessions/update/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      })
      if (res.ok) {
        setSessions((prev) =>
          prev.map((s) => (s.id === sessionId ? { ...s, title } : s))
        )
      }
    },
    []
  )

  return {
    sessions,
    currentSession,
    messages,
    loading,
    fetchSessions,
    createSession,
    loadSession,
    updateSessionTitle,
    setSessions,
    setCurrentSession,
  }
}
