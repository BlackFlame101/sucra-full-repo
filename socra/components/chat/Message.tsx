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
  const metadata = message.metadata as {
    explanation?: unknown
    explanationPreview?: boolean
    partial?: boolean
    qcm_status?: "unreviewed" | "partial" | "failed"
  } | undefined
  if (message.role === "assistant" && metadata?.explanation) return null
  const text = getTextContent(message)
  if (!text) return null

  if (message.role === "assistant") {
    return <TutorMessage content={text} isStreaming={isStreaming} partial={metadata?.partial}
      explanationPreview={metadata?.explanationPreview || Boolean(metadata?.qcm_status)} />
  }
  return <StudentMessage content={text} />
}
