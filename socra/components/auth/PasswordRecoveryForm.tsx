"use client"

import { useState, type FormEvent } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { createClient } from "@/lib/supabase/client"

export function PasswordRecoveryForm({ mode }: { mode: "request" | "reset" }) {
  const resetting = mode === "reset"
  const [value, setValue] = useState("")
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState("")
  const [error, setError] = useState("")
  const [sent, setSent] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError("")
    try {
      if (resetting) {
        const response = await fetch("/api/auth/reset-password", { method: "POST",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: value }) })
        if (!response.ok) throw new Error((await response.json()).error || "Could not update your password.")
        window.location.assign("/dashboard")
      } else {
        const callback = new URL("/auth/callback?next=/reset-password", window.location.origin)
        const { error: authError } = await createClient().auth.resetPasswordForEmail(value.trim(), { redirectTo: callback.href })
        if (authError && authError.status === 429) throw new Error("Too many requests. Wait before trying again.")
        if (authError && (!authError.status || authError.status >= 500)) throw new Error("Password recovery is temporarily unavailable.")
        setSent(true)
        setNotice("If the address is registered, check your email. Open the reset link in this browser.")
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not complete the request.")
    } finally {
      setBusy(false)
    }
  }

  return <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 px-6">
    <h1 className="font-serif text-3xl">{resetting ? "Choose a new password" : "Reset your password"}</h1>
    {!resetting && <p className="text-sm text-muted-foreground">Enter your email to receive a link. If a previous link expired, request a new one here.</p>}
    {notice && <p role="status" className="text-sm text-muted-foreground">{notice}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!sent && <form className="space-y-4" onSubmit={submit}>
      <Label htmlFor="recovery-value">{resetting ? "New password" : "Email address"}</Label>
      <Input id="recovery-value" type={resetting ? "password" : "email"} value={value}
        onChange={(event) => setValue(event.target.value)} minLength={resetting ? 8 : undefined}
        maxLength={resetting ? 128 : 320} autoComplete={resetting ? "new-password" : "email"} required />
      <Button disabled={busy} type="submit">{busy ? "Please wait" : resetting ? "Update password" : "Send reset link"}</Button>
    </form>}
    <Link className="text-sm text-secondary underline" href={resetting ? "/forgot-password" : "/login"}>
      {resetting ? "Request another reset link" : "Back to sign in"}
    </Link>
  </main>
}
