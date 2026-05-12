"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Search, Bell, User } from "lucide-react"

const navLinks = [
  { label: "Home", href: "#hero", sectionId: "hero" },
  { label: "Methodology", href: "#features", sectionId: "features" },
  { label: "Curriculum", href: "#modern-scholar", sectionId: "modern-scholar" },
  { label: "Contact", href: "#contact", sectionId: "contact" },
]

export function Navbar() {
  const [activeSection, setActiveSection] = useState("hero")

  useEffect(() => {
    const handleScroll = () => {
      const scrollPosition = window.scrollY + window.innerHeight / 3

      // Check if we're at the bottom of the page
      const isAtBottom = window.innerHeight + window.scrollY >= document.body.offsetHeight - 100

      if (isAtBottom) {
        setActiveSection("contact")
        return
      }

      // Find the current section
      for (let i = navLinks.length - 1; i >= 0; i--) {
        const element = document.getElementById(navLinks[i].sectionId)
        if (element) {
          const offsetTop = element.offsetTop
          if (scrollPosition >= offsetTop) {
            setActiveSection(navLinks[i].sectionId)
            return
          }
        }
      }

      setActiveSection("hero")
    }

    window.addEventListener("scroll", handleScroll)
    handleScroll()

    return () => window.removeEventListener("scroll", handleScroll)
  }, [])

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto flex h-14 max-w-7xl items-center px-4">
        <div className="flex-1">
          <Link href="/" className="flex items-center">
            <span className="font-serif text-xl font-semibold italic">Socra</span>
          </Link>
        </div>

        <nav className="hidden md:flex items-center gap-8">
          {navLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className={`relative py-4 font-serif text-sm transition-colors ${
                activeSection === link.sectionId
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {link.label}
              {activeSection === link.sectionId && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-foreground" />
              )}
            </a>
          ))}
        </nav>

        <div className="flex-1 flex items-center justify-end gap-2">
          <Button variant="ghost" size="icon" className="hidden md:inline-flex">
            <Search className="h-4 w-4" />
            <span className="sr-only">Search</span>
          </Button>
          <Button variant="ghost" size="icon" className="hidden md:inline-flex">
            <Bell className="h-4 w-4" />
            <span className="sr-only">Notifications</span>
          </Button>
          <Button variant="ghost" size="icon" asChild>
            <Link href="/login">
              <User className="h-4 w-4" />
              <span className="sr-only">Account</span>
            </Link>
          </Button>
        </div>
      </div>
    </header>
  )
}
