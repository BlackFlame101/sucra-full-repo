"use client"

import { DashboardNavbar } from "@/components/layout/DashboardNavbar"
import { ErrorBoundary } from "@/components/ErrorBoundary"

interface DashboardShellProps {
  user: {
    name: string
    email: string
    avatarUrl?: string
  }
  children: React.ReactNode
}

export function DashboardShell({ user, children }: DashboardShellProps) {
  return (
    <div className="min-h-screen bg-background">
      <DashboardNavbar user={user} />
      <main>
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </div>
  )
}
