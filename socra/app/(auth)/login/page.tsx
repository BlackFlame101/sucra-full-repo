import { Metadata } from "next"
import Link from "next/link"
import { LoginForm } from "@/components/auth/LoginForm"
import { Settings } from "lucide-react"

export const metadata: Metadata = {
  title: "Sign In",
  description: "Sign in to your Socra account and continue your journey of inquiry.",
}

export default function LoginPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="fixed top-0 left-0 right-0 z-50 border-b border-border/30 bg-background/80 backdrop-blur-sm">
        <div className="container mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="font-serif text-xl italic font-medium">
            Socra
          </Link>
          <Link
            href="/login"
            className="text-xs font-medium uppercase tracking-widest text-foreground hover:text-secondary transition-colors"
          >
            Scholar Login
          </Link>
        </div>
      </header>

      {/* Main Content */}
      <main className="pt-16 min-h-screen flex">
        {/* Left Side - Image & Quote */}
        <div className="hidden lg:flex lg:w-1/2 relative">
          <div className="absolute inset-0 m-8">
            <div className="relative h-full w-full rounded-2xl overflow-hidden bg-gradient-to-b from-slate-800/20 to-slate-900/80">
              {/* Background gradient effect */}
              <div className="absolute inset-0 bg-gradient-to-t from-background via-transparent to-transparent" />
              
              {/* Cloud/Mountain imagery effect */}
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-80 h-96 bg-gradient-to-t from-slate-400/30 via-slate-300/20 to-slate-200/10 rounded-full blur-3xl" />
              </div>
              
              {/* Quote overlay */}
              <div className="absolute bottom-0 left-0 right-0 p-8">
                <p className="text-xs font-medium uppercase tracking-widest text-secondary mb-4">
                  The Quest for Wisdom
                </p>
                <blockquote className="font-serif text-3xl italic text-foreground/90 leading-relaxed mb-4">
                  &ldquo;The unexamined life is not worth living.&rdquo;
                </blockquote>
                <p className="text-muted-foreground">— Socrates</p>
              </div>
            </div>
          </div>
        </div>

        {/* Right Side - Login Form */}
        <div className="w-full lg:w-1/2 flex flex-col items-center justify-center px-6 py-12">
          <div className="w-full max-w-md space-y-8">
            {/* Icon */}
            <div className="flex justify-center lg:justify-start">
              <div className="w-16 h-16 rounded-xl bg-card border border-border/50 flex items-center justify-center">
                <Settings className="w-6 h-6 text-muted-foreground" />
              </div>
            </div>

            {/* Title */}
            <div className="space-y-2 text-center lg:text-left">
              <h1 className="font-serif text-4xl font-medium text-foreground">
                Return to the Atelier
              </h1>
              <p className="text-muted-foreground">
                Continue your journey of inquiry.
              </p>
            </div>

            {/* Form */}
            <LoginForm />

            {/* Footer */}
            <div className="pt-8 flex justify-center text-xs font-medium uppercase tracking-widest text-muted-foreground">
              <span>© {new Date().getFullYear()} Socra</span>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
