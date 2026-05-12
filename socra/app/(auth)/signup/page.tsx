import { Metadata } from "next"
import Link from "next/link"
import { SignupForm } from "@/components/auth/SignupForm"

export const metadata: Metadata = {
  title: "Sign Up",
  description: "Join Socra and begin your Socratic study companion experience.",
}

export default function SignupPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="fixed top-0 left-0 right-0 z-50 border-b border-border/30 bg-background/80 backdrop-blur-sm">
        <div className="container mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="font-serif text-xl italic font-medium">
            Socratic Atelier
          </Link>
          <Link
            href="/login"
            className="text-sm font-medium text-secondary hover:text-secondary/80 transition-colors"
          >
            Scholar Login
          </Link>
        </div>
      </header>

      {/* Main Content */}
      <main className="pt-16 min-h-screen flex flex-col items-center justify-center px-6 py-12">
        <div className="w-full max-w-6xl flex flex-col lg:flex-row items-center gap-12 lg:gap-24">
          {/* Left Side - Form */}
          <div className="w-full lg:w-1/2 flex flex-col items-center">
            {/* Title */}
            <div className="space-y-3 text-center mb-8">
              <h1 className="font-serif text-4xl md:text-5xl italic font-medium text-foreground">
                Join the Atelier
              </h1>
              <p className="text-muted-foreground">
                Begin your Socratic study companion experience.
              </p>
            </div>

            {/* Form Card */}
            <div className="w-full max-w-md p-8 rounded-2xl border border-border/50 bg-card/50 backdrop-blur-sm">
              <SignupForm />
            </div>
          </div>

          {/* Right Side - Book Card */}
          <div className="hidden lg:block lg:w-1/3">
            <div className="rounded-2xl border border-border/50 bg-card/50 backdrop-blur-sm overflow-hidden">
              {/* Book Image Placeholder */}
              <div className="h-64 bg-gradient-to-b from-slate-600/30 to-slate-800/50 flex items-center justify-center">
                <div className="relative w-48 h-56">
                  {/* Stacked books effect */}
                  <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-40 space-y-1">
                    {[...Array(8)].map((_, i) => (
                      <div
                        key={i}
                        className="h-5 bg-gradient-to-r from-slate-500/60 to-slate-600/60 rounded-sm"
                        style={{
                          width: `${100 - i * 5}%`,
                          marginLeft: `${i * 2.5}%`,
                        }}
                      />
                    ))}
                  </div>
                </div>
              </div>
              
              {/* Book Info */}
              <div className="p-6 space-y-2">
                <h3 className="font-serif text-lg italic text-foreground">
                  The Socratic Method
                </h3>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  &ldquo;THE ONLY TRUE WISDOM IS IN KNOWING YOU KNOW NOTHING.&rdquo;
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="mt-12 text-center text-xs font-medium uppercase tracking-widest text-muted-foreground">
          © 2026 Socra
        </footer>
      </main>
    </div>
  )
}
