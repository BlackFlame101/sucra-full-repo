"use client"

import { useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"

interface CreateCourseModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (name: string, description?: string) => Promise<void>
}

export function CreateCourseModal({
  open,
  onOpenChange,
  onSubmit,
}: CreateCourseModalProps) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return

    setSubmitting(true)
    setError(null)

    try {
      await onSubmit(name, description || undefined)
      setName("")
      setDescription("")
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create course")
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = (nextOpen: boolean) => {
    if (!submitting) {
      onOpenChange(nextOpen)
      if (!nextOpen) {
        setName("")
        setDescription("")
        setError(null)
      }
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogDescription className="uppercase text-xs tracking-widest font-medium text-muted-foreground">
              New Course
            </DialogDescription>
            <DialogTitle className="font-serif text-xl font-medium">
              Expand the Atelier
            </DialogTitle>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label
                htmlFor="course-name"
                className="uppercase text-xs tracking-widest text-muted-foreground"
              >
                Course Name
              </Label>
              <Input
                id="course-name"
                placeholder="e.g. Advanced Macroeconomics"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={submitting}
                autoFocus
              />
            </div>
            <div className="grid gap-2">
              <Label
                htmlFor="course-description"
                className="uppercase text-xs tracking-widest text-muted-foreground"
              >
                Description
                <span className="normal-case tracking-normal text-muted-foreground/60 font-normal ml-1">
                  (optional)
                </span>
              </Label>
              <Textarea
                id="course-description"
                placeholder="Brief description of the course..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                disabled={submitting}
                className="min-h-[80px]"
              />
            </div>

            {error && (
              <p className="text-sm text-destructive">{error}</p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => handleClose(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting || !name.trim()}>
              {submitting ? "Creating..." : "Start Inquiring"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
