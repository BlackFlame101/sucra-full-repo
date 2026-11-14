import { createClient } from "@/lib/supabase/server"
import { NextResponse } from "next/server"

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get("code")
  const recovery = searchParams.get("next") === "/reset-password"

  if (code) {
    const client = await createClient()
    const { error, data } = await client.auth.exchangeCodeForSession(code)
    if (!error && data.session) {
      if (!recovery) return NextResponse.redirect(new URL("/dashboard", origin))
      if ("redirectType" in data && data.redirectType === "recovery") {
        const { data: claimsData } = await client.auth.getClaims(data.session.access_token)
        const sessionId = claimsData?.claims?.session_id
        if (typeof sessionId === "string") {
          const response = NextResponse.redirect(new URL("/reset-password", origin))
          response.cookies.set("socra_recovery", sessionId, {
            httpOnly: true, secure: new URL(origin).protocol === "https:", sameSite: "lax", path: "/", maxAge: 600,
          })
          return response
        }
      }
    }
  }

  return NextResponse.redirect(new URL(recovery ? "/forgot-password?error=expired" : "/login?error=auth_callback_error", origin))
}
