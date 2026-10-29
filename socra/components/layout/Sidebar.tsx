"use client"

import { useState, useRef, useEffect, type KeyboardEvent } from "react"
import Link from "next/link"
import {
  Plus,
  FileText,
  MessageCircle,
  Settings,
  HelpCircle,
  Pencil,
  Check,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import type { CourseSession, Document } from "@/types"

interface SidebarProps {
  courseName: string
  courseId: string
  documents: Document[]
  sessions: CourseSession[]
  currentSessionId?: string
  onNewInquiry: () => void
  onSettingsOpen?: () => void
  onRenameSession?: (sessionId: string, newTitle: string) => void
}

export function Sidebar({
  courseName,
  courseId,
  documents,
  sessions,
  currentSessionId,
  onNewInquiry,
  onSettingsOpen,
  onRenameSession,
}: SidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState("")
  const editInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus()
      editInputRef.current.select()
    }
  }, [editingId])

  const startEditing = (session: CourseSession) => {
    setEditingId(session.id)
    setEditValue(session.title || "Untitled")
  }

  const commitRename = () => {
    if (editingId && editValue.trim() && onRenameSession) {
      onRenameSession(editingId, editValue.trim())
    }
    setEditingId(null)
  }

  const cancelEditing = () => {
    setEditingId(null)
  }

  const handleEditKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault()
      commitRename()
    } else if (e.key === "Escape") {
      e.preventDefault()
      cancelEditing()
    }
  }

  return (
    <div className="flex h-full flex-col border-r border-border/40 bg-card/30">
      {/* Course Header */}
      <div className="p-4 pb-2">
        <Link
          href={`/dashboard/course/${courseId}`}
          className="group flex items-center gap-2"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-tertiary/10">
            <FileText className="h-4 w-4 text-tertiary" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold uppercase tracking-wider truncate">
              {courseName}
            </h2>
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
              Academic Year {new Date().getFullYear()}
            </p>
          </div>
        </Link>
      </div>

      {/* New Inquiry Button */}
      <div className="px-4 py-2">
        <Button
          onClick={onNewInquiry}
          className="w-full gap-2 bg-secondary/15 text-secondary hover:bg-secondary/25 border border-secondary/20"
          variant="outline"
        >
          <Plus className="h-4 w-4" />
          New Inquiry
        </Button>
      </div>

      <div className="min-h-0 w-full min-w-0 flex-1 overflow-x-hidden overflow-y-auto px-4">
        {/* Resources Section */}
        <div className="py-3">
          <h3 className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
            Resources (PDFs)
          </h3>
          <div className="space-y-0.5">
            {documents.length === 0 ? (
              <p className="text-xs text-muted-foreground/60 py-2">
                No documents uploaded
              </p>
            ) : (
              documents.map((doc) => (
                <div
                  key={doc.id}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                >
                  <FileText className="h-3.5 w-3.5 shrink-0 text-tertiary/70" />
                  <span className="truncate text-xs">{doc.filename}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Recent Inquiries Section */}
        <div className="w-full min-w-0 py-3 border-t border-border/30">
          <h3 className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
            Recent Inquiries
          </h3>
          <div className="w-full min-w-0 space-y-0.5">
            {sessions.length === 0 ? (
              <p className="text-xs text-muted-foreground/60 py-2">
                No inquiries yet
              </p>
            ) : (
              sessions.slice(0, 10).map((session) => {
                const isActive = session.id === currentSessionId
                const isEditing = editingId === session.id

                if (isEditing) {
                  return (
                    <div
                      key={session.id}
                      className="flex items-center gap-1 rounded-md px-2 py-1"
                    >
                      <MessageCircle className="h-3.5 w-3.5 shrink-0 text-secondary" />
                      <input
                        ref={editInputRef}
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={handleEditKeyDown}
                        onBlur={commitRename}
                        className="flex-1 min-w-0 bg-muted/50 border border-border/50 rounded px-1.5 py-0.5 text-xs outline-none focus:border-secondary/50"
                      />
                      <button
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={commitRename}
                        className="p-0.5 text-secondary hover:text-secondary/80"
                      >
                        <Check className="h-3 w-3" />
                      </button>
                      <button
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={cancelEditing}
                        className="p-0.5 text-muted-foreground hover:text-foreground"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  )
                }

                return (
                  <div
                    key={session.id}
                    className={`group/session grid w-full min-w-0 box-border grid-cols-[minmax(0,1fr)_2rem] items-center gap-1 rounded-md px-2 py-1.5 text-xs transition-colors ${
                      isActive
                        ? "bg-secondary/15 text-secondary font-medium"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                    }`}
                  >
                    <Link
                      href={session.exam_id
                        ? `/dashboard/course/${courseId}/exam/${session.id}?restore=1`
                        : `/dashboard/course/${courseId}/inquiry/${session.id}`}
                      className="flex min-w-0 items-center gap-2 overflow-hidden"
                    >
                      <MessageCircle
                        className={`h-3.5 w-3.5 shrink-0 ${
                          isActive ? "text-secondary" : ""
                        }`}
                      />
                      <span className="truncate">{session.title || "Untitled"}</span>
                    </Link>
                    {onRenameSession && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          startEditing(session)
                        }}
                        type="button"
                        aria-label={`Rename ${session.title || "inquiry"}`}
                        title="Rename inquiry"
                        className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border/40 bg-background/60 text-muted-foreground shadow-sm transition-colors hover:border-tertiary/50 hover:bg-tertiary/15 hover:text-tertiary focus-visible:border-tertiary/50 focus-visible:bg-tertiary/15 focus-visible:text-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-tertiary/70"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                )
              })
            )}
          </div>
        </div>
      </div>

      {/* Bottom Links */}
      <div className="border-t border-border/30 p-4 space-y-0.5">
        <button
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          onClick={onSettingsOpen}
        >
          <Settings className="h-3.5 w-3.5" />
          Settings
        </button>
        <button
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          disabled
        >
          <HelpCircle className="h-3.5 w-3.5" />
          Support
        </button>
      </div>
    </div>
  )
}
