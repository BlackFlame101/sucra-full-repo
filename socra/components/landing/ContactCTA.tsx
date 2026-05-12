"use client"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Mail, Send } from "lucide-react"

export function ContactCTA() {
  return (
    <section id="contact" className="py-20 md:py-32 bg-muted/30">
      <div className="container mx-auto max-w-7xl px-4">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="font-serif text-3xl md:text-4xl font-bold mb-4">
            Enter the Atelier.
          </h2>
          <p className="text-muted-foreground mb-8">
            Have questions about Socra? Want to learn more about how it can transform your learning experience? Get in touch with us.
          </p>
          
          <form className="space-y-4 text-left">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="name" className="sr-only">
                  Name
                </label>
                <Input
                  id="name"
                  name="name"
                  placeholder="Your name"
                  className="bg-background"
                />
              </div>
              <div>
                <label htmlFor="email" className="sr-only">
                  Email
                </label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="Your email"
                  className="bg-background"
                />
              </div>
            </div>
            <div>
              <label htmlFor="message" className="sr-only">
                Message
              </label>
              <Textarea
                id="message"
                name="message"
                placeholder="Your message..."
                rows={4}
                className="bg-background resize-none"
              />
            </div>
            <div className="flex flex-col sm:flex-row gap-4 justify-center pt-4">
              <Button type="submit" size="lg" className="gap-2">
                <Send className="h-4 w-4" />
                Send Message
              </Button>
              <Button variant="outline" size="lg" asChild className="gap-2">
                <a href="mailto:contact@socra.app">
                  <Mail className="h-4 w-4" />
                  Email Us Directly
                </a>
              </Button>
            </div>
          </form>
        </div>
      </div>
    </section>
  )
}
