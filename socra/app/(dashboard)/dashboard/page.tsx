"use client"

import { useState } from "react"
import { Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { CourseList } from "@/components/course/CourseList"
import { CreateCourseModal } from "@/components/course/CreateCourseModal"
import { useCourses } from "@/hooks/useCourses"
import { useAuth } from "@/hooks/useAuth"
import { toast } from "sonner"

export default function DashboardPage() {
  const { user } = useAuth()
  const { courses, loading, createCourse, deleteCourse } = useCourses()
  const [createOpen, setCreateOpen] = useState(false)

  const userName = user?.user_metadata?.full_name || "Scholar"

  const handleCreate = async (name: string, description?: string) => {
    await createCourse(name, description)
    toast.success("Course created", {
      description: `"${name}" has been added to your atelier.`,
    })
  }

  const handleDelete = async (id: string) => {
    const course = courses.find((c) => c.id === id)
    try {
      await deleteCourse(id)
      toast.success("Course deleted", {
        description: course
          ? `"${course.name}" has been removed.`
          : "Course removed.",
      })
    } catch {
      toast.error("Failed to delete course")
    }
  }

  return (
    <div className="container mx-auto max-w-7xl px-4 sm:px-6 py-8 sm:py-12">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-10">
        <div>
          <h1 className="font-serif text-3xl sm:text-4xl font-medium mb-2 tracking-tight">
            Welcome back, {userName}
          </h1>
          <p className="text-muted-foreground text-sm sm:text-base">
            Continue your journey of inquiry.
          </p>
        </div>
        <Button className="w-fit gap-2" onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          New Course
        </Button>
      </div>

      {/* Course Grid */}
      <CourseList
        courses={courses}
        loading={loading}
        onDelete={handleDelete}
        onCreateClick={() => setCreateOpen(true)}
      />

      {/* Create Modal */}
      <CreateCourseModal
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSubmit={handleCreate}
      />
    </div>
  )
}
