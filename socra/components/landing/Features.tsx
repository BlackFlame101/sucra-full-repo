"use client"

import { Upload, MessageCircleQuestion, GraduationCap } from "lucide-react"

const features = [
  {
    icon: Upload,
    title: "Upload",
    description:
      "Share your lecture notes, dense textbooks, or research papers. Socra digests the material to understand it in its core concepts.",
    content: (
      <div className="mt-4 rounded-lg border border-border bg-muted/30 p-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <div className="h-4 w-4 rounded border border-dashed border-muted-foreground/50 flex items-center justify-center">
            <span className="text-[8px]">+</span>
          </div>
          <span>DROP FILES OR BROWSE</span>
        </div>
      </div>
    ),
  },
  {
    icon: MessageCircleQuestion,
    title: "Inquire",
    description:
      "Instead of providing answers, Socra asks probing questions that force you to synthesize information and identify gaps in your logic.",
    content: (
      <div className="mt-4 space-y-2">
        <p className="text-xs text-secondary">
          "What assumptions are you making about X?"
        </p>
        <p className="text-xs text-muted-foreground">
          Consider the implications...
        </p>
      </div>
    ),
    link: {
      text: "How does the Socratic method work in practice?",
      href: "#methodology",
    },
  },
  {
    icon: GraduationCap,
    title: "Master",
    description:
      "Solidify your understanding. Once you can explain a concept from first principles, Socra confirms your mastery and archives the insight.",
    content: null,
  },
]

export function Features() {
  return (
    <section id="features" className="py-20 md:py-32 bg-muted/30">
      <div className="container mx-auto max-w-7xl px-4">
        <div className="mb-12">
          <p className="text-xs font-medium text-secondary uppercase tracking-widest mb-2">
            THE METHODOLOGY
          </p>
          <h2 className="font-serif text-3xl md:text-4xl font-bold">
            The Path to Mastery
          </h2>
        </div>

        <div className="grid gap-8 md:grid-cols-3">
          {features.map((feature) => (
            <div
              key={feature.title}
              className="relative rounded-xl border border-border bg-card p-6 transition-colors hover:border-border/80"
            >
              <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
                <feature.icon className="h-5 w-5 text-secondary" />
              </div>
              <h3 className="text-lg font-semibold mb-2">{feature.title}</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">
                {feature.description}
              </p>
              {feature.content}
              {feature.link && (
                <a
                  href={feature.link.href}
                  className="mt-4 inline-block text-xs text-secondary hover:underline"
                >
                  {feature.link.text}
                </a>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
