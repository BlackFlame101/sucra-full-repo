"use client"

import { TutorMessage } from "./TutorMessage"
import { StudentMessage } from "./StudentMessage"
import type { UIMessage } from "ai"

interface MessageProps {
  message: UIMessage
  isStreaming?: boolean
}

function getTextContent(message: UIMessage): string {
  return message.parts
    .filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text)
    .join("")
}

export function Message({ message, isStreaming }: MessageProps) {
  const text = getTextContent(message)
  if (!text) return null

  if (message.role === "assistant") {
    return <TutorMessage content={text} isStreaming={isStreaming} />
  }
  return <StudentMessage content={text} />
}
