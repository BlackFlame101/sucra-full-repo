import { NextResponse } from "next/server"
import { createClient } from "@/lib/supabase/server"

export async function proxyExamRequest(
  path: string,
  method: "GET" | "POST",
  body?: unknown,
  timeoutMs?: number,
) {
  const supabase = await createClient()
  const [{ data: { user } }, { data: { session } }] = await Promise.all([
    supabase.auth.getUser(),
    supabase.auth.getSession(),
  ])
  if (!user || !session?.access_token) {
    return NextResponse.json({ detail: "Sign in to use exams." }, { status: 401 })
  }

  try {
    const backendUrl = (process.env.SOCRA_BACKEND_URL || "http://localhost:8000").replace(/\/+$/, "")
    const response = await fetch(
      `${backendUrl}${path}`,
      {
        method,
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        ...(timeoutMs === undefined ? {} : { signal: AbortSignal.timeout(timeoutMs) }),
        cache: "no-store",
      },
    )
    const payload = await response.json().catch(() => ({ detail: "The exam service returned an unreadable response." }))
    return NextResponse.json(payload, { status: response.status })
  } catch {
    return NextResponse.json(
      { detail: "Could not reach the Socra exam service. Check that the backend is running." },
      { status: 503 },
    )
  }
}
