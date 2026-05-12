import type { Metadata } from "next"
import { newsreader, manrope } from "@/lib/fonts"
import { Providers } from "@/components/providers"
import "./globals.css"

export const metadata: Metadata = {
  title: {
    default: "Socra - AI Tutoring Platform",
    template: "%s | Socra",
  },
  description:
    "Your tutor, your materials — Learn through Socratic dialogue using your own course PDFs.",
  keywords: [
    "AI tutor",
    "Socratic method",
    "education",
    "learning",
    "PDF study",
    "course materials",
  ],
  authors: [{ name: "Socra" }],
  creator: "Socra",
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "https://socra.app",
    title: "Socra - AI Tutoring Platform",
    description:
      "Your tutor, your materials — Learn through Socratic dialogue using your own course PDFs.",
    siteName: "Socra",
  },
  twitter: {
    card: "summary_large_image",
    title: "Socra - AI Tutoring Platform",
    description:
      "Your tutor, your materials — Learn through Socratic dialogue using your own course PDFs.",
  },
  robots: {
    index: true,
    follow: true,
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      className={`${newsreader.variable} ${manrope.variable}`}
      suppressHydrationWarning
      data-scroll-behavior="smooth"
    >
      <body className="min-h-screen bg-background antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
