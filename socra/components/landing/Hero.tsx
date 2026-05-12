"use client"

import Link from "next/link"
import { Button } from "@/components/ui/button"
import { ArrowRight } from "lucide-react"

export function Hero() {
  return (
    <section id="hero" className="relative py-20 md:py-32">
      <div className="container mx-auto max-w-7xl px-4">
        <div className="grid gap-12 lg:grid-cols-2 lg:gap-8 items-center">
          <div className="max-w-xl">
            <h1 className="font-serif text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight leading-[1.1]">
              Learn by{" "}
              <span className="italic">thinking</span>, not memorizing.
            </h1>
            <p className="mt-6 text-lg text-muted-foreground leading-relaxed">
              Your Socratic study companion for deep academic inquiry. Engage with an AI tutor that challenges your assumptions and guides you to the truth.
            </p>
            <div className="mt-8 flex flex-wrap gap-4">
              <Button asChild size="lg" className="gap-2">
                <Link href="/signup">
                  Start Learning
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
              <Button variant="outline" size="lg" asChild>
                <Link href="/signup">Try Demo</Link>
              </Button>
            </div>
          </div>
          
          <div className="relative">
            <div className="rounded-xl border border-border bg-card p-6 shadow-lg">
              <div className="flex items-center gap-2 mb-4">
                <div className="h-2 w-2 rounded-full bg-secondary" />
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Socratic Dialogue
                </span>
              </div>
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 h-8 w-8 rounded-full bg-secondary/20 flex items-center justify-center">
                    <span className="text-xs font-semibold text-secondary">S</span>
                  </div>
                  <div className="flex-1 rounded-lg bg-muted/50 p-4">
                    <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">@asking/followup</p>
                    <p className="font-serif italic text-sm leading-relaxed">
                      "You say that Justice is simply returning what is owed. But if a friend lent you a weapon while sane, and asked for it back while in a rage—would it be just to return it?"
                    </p>
                  </div>
                </div>
              </div>
              <div className="mt-6 flex items-center justify-between text-xs text-muted-foreground">
                <span>PLATO'S REPUBLIC</span>
                <span className="flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-secondary animate-pulse" />
                  IN PROGRESS
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
