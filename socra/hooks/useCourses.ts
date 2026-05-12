"use client"

import { useCallback, useEffect, useState } from "react"
import type { Course } from "@/types"

export interface CourseWithCount extends Course {
  documents: { count: number }[]
}

export function useCourses() {
  const [courses, setCourses] = useState<CourseWithCount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchCourses = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const res = await fetch("/api/courses")
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error || "Failed to fetch courses")
      }
      const data = await res.json()
      setCourses(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong")
    } finally {
      setLoading(false)
    }
  }, [])

  const createCourse = useCallback(
    async (name: string, description?: string) => {
      const res = await fetch("/api/courses", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description }),
      })

      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error || "Failed to create course")
      }

      const course = await res.json()
      setCourses((prev) => [{ ...course, documents: [{ count: 0 }] }, ...prev])
      return course
    },
    []
  )

  const deleteCourse = useCallback(async (id: string) => {
    const res = await fetch(`/api/courses/${id}`, { method: "DELETE" })

    if (!res.ok) {
      const data = await res.json()
      throw new Error(data.error || "Failed to delete course")
    }

    setCourses((prev) => prev.filter((c) => c.id !== id))
  }, [])

  useEffect(() => {
    fetchCourses()
  }, [fetchCourses])

  return { courses, loading, error, fetchCourses, createCourse, deleteCourse }
}
