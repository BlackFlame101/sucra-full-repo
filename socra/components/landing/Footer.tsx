"use client"

import Link from "next/link"

const footerLinks = [
  { label: "Privacy", href: "/privacy" },
  { label: "Terms", href: "/terms" },
  { label: "Twitter", href: "https://twitter.com/socra" },
]

export function Footer() {
  return (
    <footer className="border-t border-border py-8">
      <div className="container mx-auto max-w-7xl px-4">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-serif text-lg font-semibold italic">Socra</span>
            <span className="text-xs text-muted-foreground">
              © 2024 Digital Atelier Education
            </span>
          </div>

          <nav className="flex items-center gap-6">
            {footerLinks.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {link.label}
              </Link>
            ))}
          </nav>

          <div className="text-xs text-muted-foreground">
            All rights reserved.
          </div>
        </div>
      </div>
    </footer>
  )
}
