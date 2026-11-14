import { createClient } from "@/lib/supabase/server"
import { NextResponse } from "next/server"

export async function POST() {
  const supabase = await createClient()
  const { error } = await supabase.auth.signOut()
  if (error) return NextResponse.json({ error: "Could not sign out. Please try again." }, { status: 503 })

  const response = new NextResponse(null, { status: 204, headers: { "Cache-Control": "no-store" } })
  response.cookies.delete("socra_recovery")
  return response
}
