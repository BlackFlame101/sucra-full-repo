import {
  Navbar,
  Hero,
  Features,
  ModernScholar,
  ContactCTA,
  Footer,
} from "@/components/landing"

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main className="flex-1">
        <Hero />
        <Features />
        <ModernScholar />
        <ContactCTA />
      </main>
      <Footer />
    </div>
  )
}
