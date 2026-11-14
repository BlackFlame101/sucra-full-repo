import { createClient } from "@/lib/supabase/server"
import { NextResponse } from "next/server"

export async function POST(request: Request) {
  const supabase = await createClient()
  await supabase.auth.signOut()
  
  const url = new URL("/login", request.url)
  const response = NextResponse.redirect(url, 303)
  response.cookies.delete("socra_recovery")
  return response
}
