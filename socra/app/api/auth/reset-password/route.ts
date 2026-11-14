import { cookies } from "next/headers"
import { createClient } from "@/lib/supabase/server"

export async function POST(request: Request) {
  const body = request.headers.get("content-type")?.startsWith("application/json") ? await request.json().catch(() => null) : null
  if (typeof body?.password !== "string" || body.password.length < 8 || body.password.length > 128) {
    return Response.json({ error: "Use a password between 8 and 128 characters." }, { status: 400 })
  }
  const jar = await cookies()
  const client = await createClient()
  const { data, error } = await client.auth.getClaims()
  const claims = data?.claims
  if (error || !claims?.session_id || jar.get("socra_recovery")?.value !== claims.session_id) {
    return Response.json({ error: "The reset link expired. Request a new link." }, { status: 403 })
  }
  const result = await client.auth.updateUser({ password: body.password })
  if (result.error) return Response.json({ error: "Could not update your password. Choose a stronger password and retry." }, { status: 400 })
  jar.delete("socra_recovery")
  return Response.json({ ok: true })
}
