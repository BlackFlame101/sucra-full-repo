import { Suspense } from "react"
import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"
import { DashboardShell } from "@/components/layout/DashboardShell"

function PageFallback() {
  return (
    <div className="container mx-auto max-w-7xl px-4 sm:px-6 py-8 sm:py-12">
      <div className="animate-pulse space-y-6">
        <div className="h-10 w-64 bg-muted rounded-lg" />
        <div className="h-5 w-40 bg-muted rounded" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-8">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-40 bg-muted rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  )
}

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect("/login")
  }

  const navUser = {
    name: user.user_metadata?.full_name || user.email?.split("@")[0] || "User",
    email: user.email || "",
    avatarUrl: user.user_metadata?.avatar_url,
  }

  return (
    <DashboardShell user={navUser}>
      <Suspense fallback={<PageFallback />}>{children}</Suspense>
    </DashboardShell>
  )
}
