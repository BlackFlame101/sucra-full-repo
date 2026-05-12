"use client"

import { CourseCard } from "@/components/course/CourseCard"
import { Skeleton } from "@/components/ui/skeleton"
import { Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { CourseWithCount } from "@/hooks/useCourses"

interface CourseListProps {
  courses: CourseWithCount[]
  loading: boolean
  onDelete: (id: string) => void
  onCreateClick: () => void
}

function CourseCardSkeleton() {
  return (
    <div className="rounded-xl border border-border/50 bg-card/50 p-5">
      <Skeleton className="h-10 w-10 rounded-lg mb-3" />
      <Skeleton className="h-5 w-3/4 mb-2" />
      <Skeleton className="h-4 w-full mb-1" />
      <Skeleton className="h-4 w-2/3 mb-4" />
      <div className="flex gap-4">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-16" />
      </div>
    </div>
  )
}

export function CourseList({
  courses,
  loading,
  onDelete,
  onCreateClick,
}: CourseListProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <CourseCardSkeleton key={i} />
        ))}
      </div>
    )
  }

  if (courses.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border/50 bg-card/30 p-12 sm:p-16 text-center">
        <div className="mx-auto w-14 h-14 rounded-full bg-secondary/10 flex items-center justify-center mb-5">
          <Plus className="h-7 w-7 text-secondary" />
        </div>
        <h2 className="font-serif text-2xl font-medium mb-3">
          No courses yet
        </h2>
        <p className="text-muted-foreground mb-8 max-w-md mx-auto leading-relaxed">
          Create your first course to start uploading materials and begin your
          Socratic dialogue journey.
        </p>
        <Button size="lg" className="gap-2" onClick={onCreateClick}>
          <Plus className="h-4 w-4" />
          Create Your First Course
        </Button>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {courses.map((course) => (
        <CourseCard
          key={course.id}
          id={course.id}
          name={course.name}
          description={course.description}
          documentCount={course.documents?.[0]?.count ?? 0}
          updatedAt={course.updated_at!}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}
