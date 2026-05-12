import { NextResponse } from "next/server"
import { createClient } from "@/lib/supabase/server"

export async function POST(request: Request) {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const { courseId, title } = await request.json()

  if (!courseId) {
    return NextResponse.json({ error: "Missing courseId" }, { status: 400 })
  }

  const { data: course } = await supabase
    .from("courses")
    .select("id")
    .eq("id", courseId)
    .eq("user_id", user.id)
    .single()

  if (!course) {
    return NextResponse.json({ error: "Course not found" }, { status: 404 })
  }

  const { data: session, error } = await supabase
    .from("sessions")
    .insert({
      course_id: courseId,
      title: title || "New Inquiry",
    })
    .select()
    .single()

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  return NextResponse.json(session)
}
