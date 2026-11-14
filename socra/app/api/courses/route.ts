import { createClient } from "@/lib/supabase/server"
import { NextResponse } from "next/server"

export async function GET(request: Request) {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const courseId = new URL(request.url).searchParams.get("course")
  if (courseId && !/^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(courseId)) {
    return NextResponse.json({ error: "Invalid course." }, { status: 400 })
  }
  const query = supabase
    .from("courses")
    .select("*, documents(count)")
    .eq("user_id", user.id)
    .order("updated_at", { ascending: false })
  const { data: courses, error } = await (courseId ? query.eq("id", courseId) : query)

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  return NextResponse.json(courseId ? courses : courses.filter((course) => !("notebook_private" in course && course.notebook_private)))
}

export async function POST(request: Request) {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const body = await request.json()
  const { name, description } = body

  if (!name || typeof name !== "string" || name.trim().length === 0) {
    return NextResponse.json(
      { error: "Course name is required" },
      { status: 400 }
    )
  }

  const { data: course, error } = await supabase
    .from("courses")
    .insert({
      name: name.trim(),
      description: description?.trim() || null,
      user_id: user.id,
    })
    .select()
    .single()

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  return NextResponse.json(course, { status: 201 })
}
