"use client"

import { BookOpen, Network } from "lucide-react"

const scholarFeatures = [
  {
    icon: BookOpen,
    title: "Distraction-Free Reading",
    description:
      "A focused interface that prioritizes typography and long-form reading without the noise of typical apps.",
  },
  {
    icon: Network,
    title: "Conceptual Notebooks",
    description:
      "Every inquiry is logged as a threaded dialectic, allowing you to trace the evolution of your own understanding.",
  },
]

export function ModernScholar() {
  return (
    <section id="modern-scholar" className="py-20 md:py-32">
      <div className="container mx-auto max-w-7xl px-4">
        <div className="grid gap-12 lg:grid-cols-2 items-center">
          <div className="relative">
            <div className="relative aspect-[4/3] overflow-hidden rounded-xl">
              <div className="absolute inset-0 bg-gradient-to-br from-primary/20 to-secondary/10" />
              <div className="absolute inset-0 flex items-end p-8">
                <div className="relative">
                  <div className="absolute -left-4 top-0 bottom-0 w-1 bg-tertiary" />
                  <blockquote className="font-serif text-xl md:text-2xl italic leading-relaxed">
                    "Education is the kindling of a flame, not the filling of a vessel."
                  </blockquote>
                  <cite className="mt-4 block text-sm text-muted-foreground not-italic">
                    — SOCRATES
                  </cite>
                </div>
              </div>
              <div className="absolute inset-0 bg-[url('/images/library.jpg')] bg-cover bg-center opacity-30" />
            </div>
          </div>

          <div>
            <h2 className="font-serif text-3xl md:text-4xl font-bold italic mb-8">
              Designed for the <span className="text-secondary">Modern Scholar</span>.
            </h2>
            <div className="space-y-6">
              {scholarFeatures.map((feature) => (
                <div key={feature.title} className="flex gap-4">
                  <div className="flex-shrink-0 h-10 w-10 rounded-lg bg-secondary/10 flex items-center justify-center">
                    <feature.icon className="h-5 w-5 text-secondary" />
                  </div>
                  <div>
                    <h3 className="font-semibold mb-1">{feature.title}</h3>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {feature.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
