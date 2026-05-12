import { generateText } from "ai"
import { resolveModel, type ModelConfig } from "@/lib/ai/model-resolver"

export async function extractKeyTerms(
  messages: { role: string; content: string }[],
  modelConfig?: ModelConfig
): Promise<string[]> {
  const conversationText = messages
    .slice(-6)
    .map((m) => `${m.role}: ${m.content}`)
    .join("\n")

  try {
    const { text } = await generateText({
      model: resolveModel(modelConfig),
      system: `Extract 3-6 key academic terms or concepts from this conversation. Return ONLY a JSON array of strings — no explanation, no markdown. Example: ["Entropy","Second Law","Isolated System"]`,
      prompt: conversationText,
    })

    const cleaned = text.replace(/```json?\n?/g, "").replace(/```/g, "").trim()
    const parsed = JSON.parse(cleaned)
    return Array.isArray(parsed) ? parsed.slice(0, 8) : []
  } catch (e) {
    console.error("Key term extraction failed:", e)
    return []
  }
}

export async function extractSuggestedReadings(
  messages: { role: string; content: string }[],
  contextChunks: { filename: string; page_number: number | null; content: string }[],
  modelConfig?: ModelConfig
): Promise<
  { documentName: string; pageNumber: number; section: string; chapter?: string }[]
> {
  if (contextChunks.length === 0) return []

  const conversationText = messages
    .slice(-4)
    .map((m) => `${m.role}: ${m.content}`)
    .join("\n")

  const sourceSummary = contextChunks
    .map(
      (c) =>
        `File: ${c.filename}, Page: ${c.page_number ?? "?"}, Preview: ${c.content.slice(0, 200)}`
    )
    .join("\n")

  try {
    const { text } = await generateText({
      model: resolveModel(modelConfig),
      system: `Given a conversation and source material excerpts, suggest 1-3 specific readings the student should review. Return ONLY a JSON array with objects having: documentName, pageNumber (int), section (short description), chapter (optional short label). No markdown.`,
      prompt: `Conversation:\n${conversationText}\n\nAvailable Sources:\n${sourceSummary}`,
    })

    const cleaned = text.replace(/```json?\n?/g, "").replace(/```/g, "").trim()
    const parsed = JSON.parse(cleaned)
    return Array.isArray(parsed) ? parsed.slice(0, 3) : []
  } catch (e) {
    console.error("Suggested reading extraction failed:", e)
    return []
  }
}
