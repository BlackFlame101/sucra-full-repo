import { NextResponse } from "next/server"
import { createClient } from "@/lib/supabase/server"
import { retrieveContext } from "@/lib/ai/rag"
import { extractKeyTerms, extractSuggestedReadings } from "@/lib/ai/extract-terms"
import { isQuotaError, type ModelConfig } from "@/lib/ai/model-resolver"

export async function POST(request: Request) {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const { messages, courseId, apiKey, provider, model } = await request.json()

  if (!courseId || !messages?.length) {
    return NextResponse.json({ error: "Missing courseId or messages" }, { status: 400 })
  }

  const modelConfig: ModelConfig = {
    provider,
    model,
    apiKey,
  }

  const googleApiKey = provider === "google" ? apiKey : undefined

  const lastUserMessage = [...messages]
    .reverse()
    .find((m: { role: string }) => m.role === "user")

  try {
    const [keyTerms, ragMatches] = await Promise.all([
      extractKeyTerms(messages, modelConfig),
      lastUserMessage
        ? retrieveContext(lastUserMessage.content, courseId, 4, googleApiKey)
        : Promise.resolve([]),
    ])

    const suggestedReadings = await extractSuggestedReadings(
      messages,
      ragMatches.map((m) => ({
        filename: m.filename,
        page_number: m.page_number,
        content: m.content,
      })),
      modelConfig
    )

    return NextResponse.json({
      keyTerms,
      suggestedReadings,
    })
  } catch (error) {
    if (isQuotaError(error)) {
      return NextResponse.json(
        { error: "API quota exceeded", code: "QUOTA_EXCEEDED" },
        { status: 429 }
      )
    }
    throw error
  }
}
