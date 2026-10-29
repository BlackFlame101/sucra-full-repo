"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { BookOpen, FileText, Search, Bookmark, Trash2, ExternalLink } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type CourseRow = { id: string; name: string; description: string | null; updated_at: string }
type DocumentRow = { id: string; course_id: string; course_name: string; filename: string; file_size: number | null; page_count: number | null; created_at: string; summary_status: string }
type SavedMessage = { id: string; role: string; content: string }
type SavedQuestion = { id: string; prompt: string; exercise_type: string; concept?: string }
type SavedExam = {
  topic?: string
  status?: string
  questions?: SavedQuestion[]
  answers?: Record<string, string>
  results?: Array<{ exercise_id: string; feedback: string }>
  score?: number | null
  max_score?: number
}
type SavedSnapshot = { kind?: "inquiry" | "exam"; messages?: SavedMessage[]; exam?: SavedExam }
type SavedItem = {
  id: string
  course_id: string
  course_name: string
  item_type: "explanation" | "exercise" | "inquiry" | "exam"
  title: string
  content: Record<string, unknown>
  created_at: string
}
type LibraryData = { courses: CourseRow[]; documents: DocumentRow[]; saved_items: SavedItem[] }
type Category = "all" | "courses" | "documents" | "saved"

export default function LibraryPage() {
  const [data, setData] = useState<LibraryData>({ courses: [], documents: [], saved_items: [] })
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState<Category>("all")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  async function load() {
    setLoading(true)
    const response = await fetch("/api/library")
    const payload = await response.json()
    if (!response.ok) setError(payload.error || "Could not load your library.")
    else { setData(payload); setError("") }
    setLoading(false)
  }
  useEffect(() => { void load() }, [])

  const normalizedQuery = query.trim().toLocaleLowerCase()
  const matches = (text: string) => !normalizedQuery || text.toLocaleLowerCase().includes(normalizedQuery)
  const courses = useMemo(() => data.courses.filter((item) => matches(`${item.name} ${item.description ?? ""}`)), [data.courses, normalizedQuery])
  const documents = useMemo(() => data.documents.filter((item) => matches(`${item.filename} ${item.course_name}`)), [data.documents, normalizedQuery])
  const savedItems = useMemo(() => data.saved_items.filter((item) => matches(`${item.title} ${item.course_name} ${item.item_type}`)), [data.saved_items, normalizedQuery])

  async function removeSaved(id: string) {
    const response = await fetch(`/api/library/${id}`, { method: "DELETE" })
    if (response.ok) setData((current) => ({ ...current, saved_items: current.saved_items.filter((item) => item.id !== id) }))
  }

  const showingCourses = category === "all" || category === "courses"
  const showingDocuments = category === "all" || category === "documents"
  const showingSaved = category === "all" || category === "saved"

  return <div className="container mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-12">
    <div className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-secondary">Your study resources</p>
        <h1 className="font-serif text-3xl font-medium sm:text-4xl">Library</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">Find your courses and materials, and keep explanations, worked answers, inquiries, and exams close at hand.</p>
      </div>
      <div className="relative w-full sm:max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search your library…" className="pl-9" aria-label="Search library" />
      </div>
    </div>

    <div className="mb-8 flex flex-wrap gap-2">
      {([["all", "Everything"], ["courses", "Courses"], ["documents", "Documents"], ["saved", "Saved items"]] as const).map(([value, label]) =>
        <Button key={value} size="sm" variant={category === value ? "default" : "outline"} onClick={() => setCategory(value)}>{label}</Button>
      )}
    </div>

    {error && <p role="alert" className="mb-5 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    {loading ? <div className="rounded-xl border border-border/50 p-8 text-sm text-muted-foreground">Loading your library…</div> : <div className="space-y-10">
      {showingCourses && <section>
        <div className="mb-4 flex items-center justify-between"><h2 className="font-serif text-2xl">Courses</h2><span className="text-xs text-muted-foreground">{courses.length}</span></div>
        {courses.length ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{courses.map((course) =>
          <Link key={course.id} href={`/dashboard/course/${course.id}`} className="group rounded-xl border border-border/60 bg-card/60 p-5 transition hover:border-secondary/40 hover:bg-card">
            <BookOpen className="mb-3 h-5 w-5 text-secondary" /><h3 className="font-medium group-hover:text-secondary">{course.name}</h3>
            <p className="mt-1 line-clamp-2 min-h-10 text-sm text-muted-foreground">{course.description || "Course workspace and uploaded materials."}</p>
            <p className="mt-4 text-xs text-muted-foreground">Updated {new Date(course.updated_at).toLocaleDateString()}</p>
          </Link>
        )}</div> : <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">No courses match your search.</p>}
      </section>}

      {showingDocuments && <section>
        <div className="mb-4 flex items-center justify-between"><h2 className="font-serif text-2xl">Documents</h2><span className="text-xs text-muted-foreground">{documents.length}</span></div>
        {documents.length ? <div className="grid gap-3 md:grid-cols-2">{documents.map((document) =>
          <Link key={document.id} href={`/dashboard/course/${document.course_id}`} className="flex items-center gap-3 rounded-xl border border-border/60 bg-card/50 p-4 transition hover:border-secondary/40">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-tertiary/10"><FileText className="h-5 w-5 text-tertiary" /></span>
            <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{document.filename}</span><span className="mt-1 block text-xs text-muted-foreground">{document.course_name} · {document.page_count ? `${document.page_count} pages` : "Processing"}</span></span>
            <ExternalLink className="h-4 w-4 shrink-0 text-muted-foreground" />
          </Link>
        )}</div> : <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">No documents match your search.</p>}
      </section>}

      {showingSaved && <section>
        <div className="mb-4 flex items-center justify-between"><h2 className="font-serif text-2xl">Saved items</h2><span className="text-xs text-muted-foreground">{savedItems.length}</span></div>
        {savedItems.length ? <div className="grid gap-4 md:grid-cols-2">{savedItems.map((item) => {
          const content = item.content as {
            snapshot?: SavedSnapshot
            session_id?: string
            definition?: string
            intuition?: string
            sections?: Array<{ heading?: string; content?: string; code?: string }>
            expected_answer?: string
            explanation?: { definition?: string; intuition?: string; sections?: Array<{ heading?: string; content?: string; code?: string }>; course_example?: string; citations?: Array<{ filename: string; page_number: number }> }
            correction?: { overall_feedback?: string; citations?: Array<{ filename: string; page_number: number }> }
            solution?: { expected_answer?: string; common_mistakes?: string[] }
          }
          const snapshot = content.snapshot
          const preview = snapshot?.kind === "inquiry"
            ? snapshot.messages?.[0]?.content || "Saved inquiry transcript."
            : snapshot?.kind === "exam"
              ? `${snapshot.exam?.topic || "Course exam"}${snapshot.exam?.score != null ? ` · Score ${snapshot.exam.score}/${snapshot.exam.max_score ?? "?"}` : ""}`
              : content.explanation?.definition || content.solution?.expected_answer || content.definition || content.expected_answer || content.explanation?.sections?.[0]?.content || content.sections?.[0]?.content || content.intuition || "Saved from a study session."
          const sources = content.explanation?.citations ?? content.correction?.citations ?? []
          const itemLabel = { explanation: "Explanation", exercise: "Worked answer", inquiry: "Inquiry", exam: "Exam" }[item.item_type]

          return <article key={item.id} className="rounded-xl border border-border/60 bg-card/50 p-5">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div className="flex items-center gap-2"><Bookmark className="h-4 w-4 text-secondary" /><span className="text-xs uppercase tracking-wide text-muted-foreground">{itemLabel} · {item.course_name}</span></div>
              <Button type="button" size="icon-sm" variant="ghost" aria-label={`Remove ${item.title}`} onClick={() => void removeSaved(item.id)}><Trash2 className="h-4 w-4" /></Button>
            </div>
            <h3 className="font-medium">{item.title}</h3>
            <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{preview}</p>

            <details className="mt-4 rounded-lg border border-border/60 px-3 py-2">
              <summary className="cursor-pointer text-sm font-medium">{snapshot ? `View saved ${snapshot.kind}` : "View saved answer"}</summary>
              <div className="mt-4 space-y-4 text-sm leading-relaxed">
                {snapshot?.kind === "inquiry" && snapshot.messages?.map((message) =>
                  <div key={message.id} className="rounded-lg border border-border/50 p-3">
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{message.role === "user" ? "You" : "Socra"}</p>
                    <p className="whitespace-pre-wrap">{message.content}</p>
                  </div>
                )}
                {snapshot?.kind === "exam" && <>
                  <p className="text-muted-foreground">{snapshot.exam?.status === "completed" ? `Completed · Score ${snapshot.exam.score ?? "—"}/${snapshot.exam.max_score ?? "—"}` : "In progress"}</p>
                  {snapshot.exam?.questions?.map((question, index) => {
                    const result = snapshot.exam?.results?.find((attempt) => attempt.exercise_id === question.id)
                    return <div key={question.id} className="space-y-2 border-t border-border/50 pt-3">
                      <h4 className="font-medium">Question {index + 1} · {question.concept || question.exercise_type}</h4>
                      <p className="whitespace-pre-wrap">{question.prompt}</p>
                      <p className="text-muted-foreground">Your answer: {snapshot.exam?.answers?.[question.id] || "No answer saved"}</p>
                      {result && <p className="text-muted-foreground">{result.feedback}</p>}
                    </div>
                  })}
                </>}
                {!snapshot && content.explanation && <>
                  <p className="font-medium">{content.explanation.definition}</p>
                  {content.explanation.intuition && <p className="text-muted-foreground">{content.explanation.intuition}</p>}
                  {content.explanation.sections?.map((section, index) => <div key={index} className="space-y-2 border-t border-border/50 pt-3">
                    <h4 className="font-medium">{section.heading}</h4>
                    {section.content && <p className="whitespace-pre-wrap text-muted-foreground">{section.content}</p>}
                    {section.code && <pre className="overflow-x-auto rounded-lg bg-muted/60 p-3 text-xs"><code>{section.code}</code></pre>}
                  </div>)}
                  {content.explanation.course_example && <p className="text-muted-foreground">{content.explanation.course_example}</p>}
                </>}
                {!snapshot && !content.explanation && <>
                  <p className="whitespace-pre-wrap">{content.solution?.expected_answer || content.expected_answer || ""}</p>
                  {content.correction?.overall_feedback && <p className="text-muted-foreground">{content.correction.overall_feedback}</p>}
                  {content.solution?.common_mistakes?.length ? <ul className="list-disc space-y-1 pl-5 text-muted-foreground">{content.solution.common_mistakes.map((mistake, index) => <li key={index}>{mistake}</li>)}</ul> : null}
                </>}
                {sources.length > 0 && <div className="border-t border-border/50 pt-3">
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Course pages used</h4>
                  <ul className="space-y-1">{sources.map((source, index) => <li key={`${source.filename}-${source.page_number}-${index}`}>{source.filename} · page {source.page_number}</li>)}</ul>
                </div>}
                {content.session_id && !snapshot && <Link className="inline-block font-medium text-secondary hover:underline" href={`/dashboard/course/${item.course_id}/inquiry/${content.session_id}`}>Open original chat</Link>}
              </div>
            </details>
            <div className="mt-4 flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">Saved {new Date(item.created_at).toLocaleDateString()}</span>
              {snapshot ? <Link className="text-sm font-medium text-secondary hover:underline" href={`/dashboard/library/${item.id}`}>Open saved {snapshot.kind}</Link> : <Link className="text-sm font-medium text-secondary hover:underline" href={`/dashboard/course/${item.course_id}`}>Open course</Link>}
            </div>
          </article>
        })}</div> : <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">Explanations, worked answers, inquiries, and exams you save will appear here.</p>}
      </section>}
    </div>}
  </div>
}
