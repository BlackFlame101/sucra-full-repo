"use client"

import { useState } from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { Bell, LogOut, Settings, User as UserIcon, HelpCircle, Menu } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { ThemeToggle } from "@/components/layout/ThemeToggle"
import { SettingsDialog } from "@/components/settings/SettingsDialog"

interface NavUser {
  name: string
  email: string
  avatarUrl?: string
}

const navLinks = [
  { label: "Active Courses", href: "/dashboard", disabled: false },
  { label: "Library", href: "/dashboard/library", disabled: false },
  { label: "Notebook", href: "/dashboard/notebook", disabled: false },
]

function getInitials(name: string): string {
  return name
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase()
}

export function DashboardNavbar({ user }: { user: NavUser }) {
  const pathname = usePathname()
  const router = useRouter()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const handleSignOut = async () => {
    await fetch("/api/auth/signout", { method: "POST" })
    router.push("/login")
  }

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto flex h-14 max-w-7xl items-center px-4 sm:px-6">
        {/* Mobile menu */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="mr-2 md:hidden h-9 w-9">
              <Menu className="h-4 w-4" />
              <span className="sr-only">Menu</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-64">
            <SheetHeader>
              <SheetTitle className="font-serif text-lg italic">Socra</SheetTitle>
            </SheetHeader>
            <nav className="flex flex-col gap-1 mt-4">
              {navLinks.map((link) => (
                <Link
                  key={link.label}
                  href={link.disabled ? "#" : link.href}
                  onClick={() => setMobileOpen(false)}
                  className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    link.disabled
                      ? "text-muted-foreground/50 cursor-not-allowed"
                      : (link.href === "/dashboard" ? pathname === link.href : pathname === link.href || pathname.startsWith(link.href + "/"))
                        ? "bg-muted text-foreground"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
                >
                  {link.label}
                  {link.disabled && (
                    <span className="ml-2 text-[10px] uppercase tracking-wider text-muted-foreground/40">Soon</span>
                  )}
                </Link>
              ))}
            </nav>
          </SheetContent>
        </Sheet>

        {/* Logo */}
        <Link
          href="/dashboard"
          className="mr-8 flex items-center"
        >
          <span className="font-serif text-xl font-semibold italic tracking-tight">
            Socra
          </span>
        </Link>

        {/* Navigation Links */}
        <nav className="hidden md:flex items-center gap-1">
          {navLinks.map((link) => {
            const isActive =
              !link.disabled &&
              (link.href === "/dashboard"
                ? pathname === "/dashboard"
                : pathname === link.href || pathname.startsWith(link.href + "/"))

            if (link.disabled) {
              return (
                <Tooltip key={link.label}>
                  <TooltipTrigger asChild>
                    <span
                      className="relative px-3 py-4 text-sm font-medium text-muted-foreground/50 cursor-not-allowed select-none"
                    >
                      {link.label}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Coming soon</p>
                  </TooltipContent>
                </Tooltip>
              )
            }

            return (
              <Link
                key={link.label}
                href={link.href}
                className={`relative px-3 py-4 text-sm font-medium transition-colors ${
                  isActive
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {link.label}
                {isActive && (
                  <span className="absolute bottom-0 left-3 right-3 h-0.5 bg-foreground rounded-full" />
                )}
              </Link>
            )
          })}
        </nav>

        {/* Right Section */}
        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />

          {/* Notifications (placeholder) */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="relative h-9 w-9 text-muted-foreground hover:text-foreground"
              >
                <Bell className="h-4 w-4" />
                <span className="sr-only">Notifications</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>No new notifications</p>
            </TooltipContent>
          </Tooltip>

          {/* User Avatar Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className="relative h-9 w-9 rounded-full p-0 ml-1"
              >
                <Avatar size="default">
                  {user.avatarUrl && (
                    <AvatarImage src={user.avatarUrl} alt={user.name} />
                  )}
                  <AvatarFallback className="bg-secondary/20 text-secondary text-xs font-semibold">
                    {getInitials(user.name)}
                  </AvatarFallback>
                </Avatar>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel className="font-normal">
                <div className="flex flex-col gap-1">
                  <p className="text-sm font-medium leading-none">
                    {user.name}
                  </p>
                  <p className="text-xs leading-none text-muted-foreground">
                    {user.email}
                  </p>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuItem disabled>
                  <UserIcon className="mr-2 h-4 w-4" />
                  <span>Profile</span>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setSettingsOpen(true)}>
                  <Settings className="mr-2 h-4 w-4" />
                  <span>Settings</span>
                </DropdownMenuItem>
                <DropdownMenuItem disabled>
                  <HelpCircle className="mr-2 h-4 w-4" />
                  <span>Support</span>
                </DropdownMenuItem>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onClick={handleSignOut}
              >
                <LogOut className="mr-2 h-4 w-4" />
                <span>Sign out</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </header>
  )
}
