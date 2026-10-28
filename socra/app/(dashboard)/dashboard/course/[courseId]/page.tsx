"use client"

import { useEffect, useState, useCallback, useRef, type KeyboardEvent } from "react"
import { useParams, useRouter } from "next/navigation"
import { ArrowLeft, Plus, Upload, MessageSquare, MessageCircle, ClipboardCheck, Trash2, Pencil, Check, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { DocumentList } from "@/components/documents/DocumentList"
import { UploadModal } from "@/components/documents/UploadModal"
import { toast } from "sonner"
import type { Course, CourseSession, Document } from "@/types"
import Link from "next/link"

export default function CourseDetailPage() {
  const params = useParams<{ courseId: string }>()
  const router = useRouter()
  const courseId = params.courseId

  const [course, setCourse] = useState<Course | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [sessions, setSessions] = useState<CourseSession[]>([])
  const [loadingCourse, setLoadingCourse] = useState(true)
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [loadingSessions, setLoadingSessions] = useState(true)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null)
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState("")
  const editTitleRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editingSessionId) {
      editTitleRef.current?.focus()
      editTitleRef.current?.select()
    }
  }, [editingSessionId])

  const fetchDocuments = useCallback(async () => {
    setLoadingDocs(true)
    try {
      const res = await fetch(`/api/documents/${courseId}`)
      if (res.ok) {
        const data = await res.json()
        setDocuments(data)
      }
    } catch {
      toast.error("Failed to load documents")
    } finally {
      setLoadingDocs(false)
    }
  }, [courseId])

  useEffect(() => {
    async function fetchCourse() {
      try {
        const res = await fetch(`/api/courses`)
        if (res.ok) {
          const courses = await res.json()
          const found = courses.find(
            (c: Course & { documents: unknown }) => c.id === courseId
          )
          if (found) {
            setCourse(found)
          } else {
            router.push("/dashboard")
            return
          }
        }
      } catch {
        toast.error("Failed to load course")
      } finally {
        setLoadingCourse(false)
      }
    }

    async function fetchSessions() {
      setLoadingSessions(true)
      try {
        const res = await fetch(`/api/sessions/${courseId}`)
        if (res.ok) setSessions(await res.json())
      } catch { /* non-critical */ } finally {
        setLoadingSessions(false)
      }
    }

    fetchCourse()
    fetchDocuments()
    fetchSessions()
  }, [courseId, router, fetchDocuments])

  const handleNewInquiry = async () => {
    setCreatingSession(true)
    try {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ courseId, title: "New Inquiry" }),
      })
      if (!res.ok) throw new Error()
      const session = await res.json()
      router.push(
        `/dashboard/course/${courseId}/inquiry/${session.id}/diagnostic`
      )
    } catch {
      toast.error("Failed to create inquiry")
      setCreatingSession(false)
    }
  }

  const handleNewExam = async () => {
    setCreatingSession(true)
    try {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ courseId, title: "Mixed Course Exam" }),
      })
      if (!res.ok) throw new Error()
      const session = await res.json()
      router.push(`/dashboard/course/${courseId}/exam/${session.id}`)
    } catch {
      toast.error("Failed to create exam")
      setCreatingSession(false)
    }
  }

  const handleDeleteSession = async (session: CourseSession) => {
    const label = session.title || "this inquiry"
    if (!window.confirm(`Delete “${label}”? Its messages, exercises, and exam results will also be deleted.`)) return

    setDeletingSessionId(session.id)
    try {
      const response = await fetch(`/api/sessions/update/${encodeURIComponent(session.id)}`, {
        method: "DELETE",
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.error || "Could not delete this inquiry.")
      }
      setSessions((current) => current.filter((item) => item.id !== session.id))
      toast.success("Inquiry deleted")
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not delete this inquiry.")
    } finally {
      setDeletingSessionId(null)
    }
  }

  const saveSessionTitle = async () => {
    if (!editingSessionId) return
    const title = editingTitle.trim()
    if (!title) {
      toast.error("Enter a name for this inquiry")
      return
    }
    try {
      const response = await fetch(`/api/sessions/update/${encodeURIComponent(editingSessionId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.error || "Could not rename this inquiry.")
      }
      setSessions((current) => current.map((session) =>
        session.id === editingSessionId ? { ...session, title } : session
      ))
      setEditingSessionId(null)
      toast.success("Inquiry renamed")
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "Could not rename this inquiry.")
    }
  }

  const handleRenameKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault()
      void saveSessionTitle()
    } else if (event.key === "Escape") {
      event.preventDefault()
      setEditingSessionId(null)
    }
  }

  const handleDeleteDocument = async (id: string) => {
    const doc = documents.find((d) => d.id === id)
    try {
      const res = await fetch(`/api/documents/delete/${id}`, {
        method: "DELETE",
      })
      if (!res.ok) throw new Error()
      setDocuments((prev) => prev.filter((d) => d.id !== id))
      toast.success("Document deleted", {
        description: doc
          ? `"${doc.filename}" has been removed.`
          : "Document removed.",
      })
    } catch {
      toast.error("Failed to delete document")
    }
  }

  return (
    <div className="container mx-auto max-w-7xl px-4 sm:px-6 py-8 sm:py-12">
      {/* Back navigation */}
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to courses
      </Link>

      {/* Course Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-10">
        <div>
          {loadingCourse ? (
            <>
              <Skeleton className="h-9 w-64 mb-2" />
              <Skeleton className="h-5 w-40" />
            </>
          ) : (
            <>
              <h1 className="font-serif text-3xl sm:text-4xl font-medium mb-2 tracking-tight">
                {course?.name}
              </h1>
              {course?.description && (
                <p className="text-muted-foreground text-sm sm:text-base">
                  {course.description}
                </p>
              )}
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            className="gap-2"
            disabled={documents.length === 0 || creatingSession}
            onClick={handleNewExam}
          >
            <ClipboardCheck className="h-4 w-4" />
            Mixed Exam
          </Button>
          <Button
            variant="outline"
            className="gap-2"
            onClick={() => setUploadOpen(true)}
          >
            <Upload className="h-4 w-4" />
            Upload PDF
          </Button>
          <Button
            className="gap-2"
            disabled={documents.length === 0 || creatingSession}
            onClick={handleNewInquiry}
          >
            <MessageSquare className="h-4 w-4" />
            {creatingSession ? "Creating..." : "New Inquiry"}
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Documents Section */}
        <div className="lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="uppercase text-xs tracking-widest font-medium text-muted-foreground">
              Resources (PDFs)
            </h2>
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5 text-xs"
              onClick={() => setUploadOpen(true)}
            >
              <Plus className="h-3 w-3" />
              Add
            </Button>
          </div>
          <DocumentList
            documents={documents}
            loading={loadingDocs}
            onDelete={handleDeleteDocument}
          />
        </div>

        {/* Sidebar Info */}
        <div className="space-y-6">
          <div>
            <h2 className="uppercase text-xs tracking-widest font-medium text-muted-foreground mb-3">
              Course Stats
            </h2>
            <div className="rounded-xl border border-border/50 bg-card/40 p-4 space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Documents</span>
                <span className="font-medium">{documents.length}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Total pages</span>
                <span className="font-medium">
                  {documents.reduce(
                    (sum, d) => sum + (d.page_count ?? 0),
                    0
                  )}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Created</span>
                <span className="font-medium">
                  {course?.created_at
                    ? new Date(course.created_at).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })
                    : "—"}
                </span>
              </div>
            </div>
          </div>

          <div>
            <h2 className="uppercase text-xs tracking-widest font-medium text-muted-foreground mb-3">
              Quick Start
            </h2>
            <div className="rounded-xl border border-border/50 bg-card/40 p-4">
              <p className="text-sm text-muted-foreground leading-relaxed">
                Upload your course PDFs, then start a new inquiry to begin a
                Socratic dialogue. The tutor will reference your specific
                materials.
              </p>
            </div>
          </div>

          <div>
            <h2 className="uppercase text-xs tracking-widest font-medium text-muted-foreground mb-3">
              Recent Inquiries
            </h2>
            <div className="rounded-xl border border-border/50 bg-card/40 divide-y divide-border/30">
              {loadingSessions ? (
                <div className="p-4 space-y-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-5 w-full" />
                  ))}
                </div>
              ) : sessions.length === 0 ? (
                <div className="p-4">
                  <p className="text-sm text-muted-foreground/60">
                    No inquiries yet. Start one above.
                  </p>
                </div>
              ) : (
                sessions.map((session) => (
                  <div key={session.id} className="flex min-w-0 items-center gap-2 p-3 hover:bg-muted/30 first:rounded-t-xl last:rounded-b-xl">
                    {editingSessionId === session.id ? (
                      <>
                        <input
                          ref={editTitleRef}
                          value={editingTitle}
                          maxLength={80}
                          onChange={(event) => setEditingTitle(event.target.value)}
                          onKeyDown={handleRenameKeyDown}
                          aria-label="Inquiry name"
                          className="h-9 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-sm outline-none focus:border-secondary"
                        />
                        <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0" aria-label="Save name" onClick={() => void saveSessionTitle()}>
                          <Check className="h-4 w-4 text-secondary" />
                        </Button>
                        <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0" aria-label="Cancel rename" onClick={() => setEditingSessionId(null)}>
                          <X className="h-4 w-4" />
                        </Button>
                      </>
                    ) : (
                      <>
                        <Link
                          href={session.exam_id
                          ? `/dashboard/course/${courseId}/exam/${session.id}?restore=1`
                            : `/dashboard/course/${courseId}/inquiry/${session.id}`}
                          className="flex min-w-0 flex-1 items-center gap-3"
                        >
                          <MessageCircle className="h-4 w-4 shrink-0 text-secondary/70" />
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium truncate">
                              {session.title || "Untitled"}
                            </p>
                            <p className="text-[11px] text-muted-foreground">
                              {new Date(session.updated_at).toLocaleDateString("en-US", {
                                month: "short",
                                day: "numeric",
                                year: "numeric",
                              })}
                            </p>
                          </div>
                        </Link>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
                          aria-label={`Rename ${session.title || "inquiry"}`}
                          title="Rename inquiry"
                          onClick={() => {
                            setEditingSessionId(session.id)
                            setEditingTitle(session.title || "")
                          }}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                      </>
                    )}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      aria-label={`Delete ${session.title || "inquiry"}`}
                      title="Delete inquiry"
                      disabled={deletingSessionId === session.id || editingSessionId === session.id}
                      onClick={() => void handleDeleteSession(session)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Upload Modal */}
      <UploadModal
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        courseId={courseId}
        onUploadComplete={fetchDocuments}
      />
    </div>
  )
}
