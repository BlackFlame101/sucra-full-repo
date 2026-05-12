"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { createClient } from "@/lib/supabase/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Loader2 } from "lucide-react"

export function SignupForm() {
  const router = useRouter()
  const supabase = createClient()
  const [fullName, setFullName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    if (password.length < 6) {
      setError("Password must be at least 6 characters long.")
      setLoading(false)
      return
    }

    try {
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          data: {
            full_name: fullName,
          },
          emailRedirectTo: `${window.location.origin}/auth/callback`,
        },
      })

      if (error) {
        setError(error.message)
        return
      }

      setSuccess(true)
    } catch {
      setError("An unexpected error occurred. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="space-y-6 text-center">
        <div className="space-y-2">
          <h2 className="font-serif text-2xl font-medium text-foreground">
            Check Your Email
          </h2>
          <p className="text-muted-foreground">
            We&apos;ve sent a confirmation link to{" "}
            <span className="font-medium text-foreground">{email}</span>
          </p>
        </div>
        <p className="text-sm text-muted-foreground">
          Click the link in your email to verify your account and start your
          journey of inquiry.
        </p>
        <Button
          variant="outline"
          onClick={() => router.push("/login")}
          className="w-full h-12"
        >
          Back to Sign In
        </Button>
      </div>
    )
  }

  return (
    <form onSubmit={handleSignup} className="space-y-5">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-2">
        <Label
          htmlFor="fullName"
          className="text-xs font-medium uppercase tracking-widest text-muted-foreground"
        >
          Full Name
        </Label>
        <Input
          id="fullName"
          type="text"
          placeholder="Aristotle of Stagira"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          required
          disabled={loading}
          className="h-12 bg-card border-border/50 placeholder:text-muted-foreground/50"
        />
      </div>

      <div className="space-y-2">
        <Label
          htmlFor="email"
          className="text-xs font-medium uppercase tracking-widest text-muted-foreground"
        >
          University Email
        </Label>
        <Input
          id="email"
          type="email"
          placeholder="scholar@lyceum.edu"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={loading}
          className="h-12 bg-card border-border/50 placeholder:text-muted-foreground/50"
        />
      </div>

      <div className="space-y-2">
        <Label
          htmlFor="password"
          className="text-xs font-medium uppercase tracking-widest text-muted-foreground"
        >
          Create Password
        </Label>
        <Input
          id="password"
          type="password"
          placeholder="••••••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          disabled={loading}
          minLength={6}
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
          "Create Account"
        )}
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        Already a scholar?{" "}
        <Link
          href="/login"
          className="font-medium text-foreground hover:text-secondary transition-colors"
        >
          Sign In
        </Link>
      </p>
    </form>
  )
}
