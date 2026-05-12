"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { createClient } from "@/lib/supabase/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { ArrowRight, Loader2 } from "lucide-react"

export function LoginForm() {
  const router = useRouter()
  const supabase = createClient()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      const { error } = await supabase.auth.signInWithPassword({
        email,
        password,
      })

      if (error) {
        setError(error.message)
        return
      }

      router.push("/dashboard")
      router.refresh()
    } catch {
      setError("An unexpected error occurred. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleLogin} className="space-y-6">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-2">
        <Label
          htmlFor="email"
          className="text-xs font-medium uppercase tracking-widest text-muted-foreground"
        >
          Email Address
        </Label>
        <Input
          id="email"
          type="email"
          placeholder="scholar@atelier.edu"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={loading}
          className="h-12 bg-card border-border/50 placeholder:text-muted-foreground/50"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label
            htmlFor="password"
            className="text-xs font-medium uppercase tracking-widest text-muted-foreground"
          >
            Password
          </Label>
          <Link
            href="/forgot-password"
            className="text-xs font-medium uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
          >
            Forgot Password?
          </Link>
        </div>
        <Input
          id="password"
          type="password"
          placeholder="••••••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          disabled={loading}
          className="h-12 bg-card border-border/50 placeholder:text-muted-foreground/50"
        />
      </div>

      <Button
        type="submit"
        disabled={loading}
        className="w-full h-12 bg-secondary hover:bg-secondary/90 text-secondary-foreground font-medium uppercase tracking-widest"
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <>
            Sign In
            <ArrowRight className="ml-2 h-4 w-4" />
          </>
        )}
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        Need an account?{" "}
        <Link
          href="/signup"
          className="font-medium text-foreground hover:text-secondary transition-colors"
        >
          Sign Up
        </Link>
      </p>
    </form>
  )
}
