"use client"

import { usePathname } from "next/navigation"
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
  const pathname = usePathname()
  const isInquiry = /^\/dashboard\/course\/[^/]+\/inquiry\/[^/]+\/?$/.test(pathname)
  const isWorkspace = isInquiry || /^\/dashboard\/notebook\/?$/.test(pathname)

  return (
    <div
      data-dashboard-workspace={isWorkspace ? "" : undefined}
      className={isWorkspace ? "flex h-dvh flex-col overflow-hidden bg-background" : "min-h-screen bg-background"}
    >
      <DashboardNavbar user={user} />
      <main className={isWorkspace ? "min-h-0 flex-1 overflow-hidden" : undefined}>
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </div>
  )
}
