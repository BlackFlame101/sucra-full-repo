import type { Tables } from "@/types/database"
import type { NoteDocument } from "./document"

export type Note = Tables<"notebook_notes"> & { course_name?: string; source_filename?: string }
export type NoteCourse = { id: string; name: string }
export type NoteDraft = Pick<Note, "title" | "topic" | "course_id" | "tags" | "starred"> & { content_json: NoteDocument }
export type NoteFilter = "All" | "Courses" | "Personal" | "Starred"

export function searchNotes(notes: Note[], courses: NoteCourse[], query: string, filter: NoteFilter) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  const names = new Map(courses.map((course) => [course.id, course.name]))
  return notes.filter((note) => {
    if (filter === "Courses" && !note.course_id || filter === "Personal" && note.course_id ||
        filter === "Starred" && !note.starred) return false
    const searchable = [note.title, note.content, note.topic, ...(note.tags ?? []),
      note.course_id ? names.get(note.course_id) ?? note.course_name : "Personal"].join(" ").toLocaleLowerCase()
    return terms.every((term) => searchable.includes(term))
  })
}

export function groupNotes(notes: Note[], now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const monday = new Date(today)
  monday.setDate(today.getDate() - (today.getDay() + 6) % 7)
  const groups = { Today: [] as Note[], "This Week": [] as Note[], Earlier: [] as Note[] }
  for (const note of notes) {
    const updated = new Date(note.updated_at)
    groups[updated >= today ? "Today" : updated >= monday ? "This Week" : "Earlier"].push(note)
  }
  return Object.entries(groups)
}
