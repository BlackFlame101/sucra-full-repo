"use client"

import Link from "next/link"
import { BookOpen, Clock, MoreVertical, Trash2 } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"

interface CourseCardProps {
  id: string
  name: string
  description?: string | null
  documentCount: number
  updatedAt: string
  onDelete: (id: string) => void
}

export function CourseCard({
  id,
  name,
  description,
  documentCount,
  updatedAt,
  onDelete,
}: CourseCardProps) {
  return (
    <div className="group relative rounded-xl border border-border/50 bg-card/50 transition-all hover:border-secondary/40 hover:bg-card/80 hover:shadow-md">
      <Link
        href={`/dashboard/course/${id}`}
        className="block p-5"
      >
        <div className="flex items-start justify-between mb-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-secondary/10">
            <BookOpen className="h-5 w-5 text-secondary" />
          </div>
        </div>
        <h3 className="font-serif text-lg font-medium mb-1 group-hover:text-secondary transition-colors">
          {name}
        </h3>
        {description && (
          <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
            {description}
          </p>
        )}
        <div className="flex items-center gap-4 text-xs text-muted-foreground mt-3">
          <span className="flex items-center gap-1">
            <BookOpen className="h-3 w-3" />
            {documentCount} {documentCount === 1 ? "document" : "documents"}
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {new Date(updatedAt).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
            })}
          </span>
        </div>
      </Link>

      {/* Context menu */}
      <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="h-7 w-7">
              <MoreVertical className="h-4 w-4" />
              <span className="sr-only">Course options</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              variant="destructive"
              onClick={(e) => {
                e.stopPropagation()
                onDelete(id)
              }}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete course
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
