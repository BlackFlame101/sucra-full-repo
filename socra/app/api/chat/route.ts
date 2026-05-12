import { streamText, convertToModelMessages, type UIMessage } from "ai"
import { createClient } from "@/lib/supabase/server"
import { retrieveContext, formatContextForPrompt } from "@/lib/ai/rag"
import { buildSocraticSystemPrompt } from "@/lib/ai/socratic-prompt"
import { resolveModel, isQuotaError, type ModelConfig } from "@/lib/ai/model-resolver"

export const maxDuration = 60

export async function POST(request: Request) {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return new Response("Unauthorized", { status: 401 })
  }

  const {
    messages,
    courseId,
    sessionId,
    apiKey,
    provider,
    model,
  }: {
    messages: UIMessage[]
    courseId: string
    sessionId: string
    apiKey?: string
    provider?: string
    model?: string
  } = await request.json()

  if (!courseId || !messages?.length) {
    return new Response("Missing courseId or messages", { status: 400 })
  }

  const { data: course } = await supabase
    .from("courses")
    .select("name")
    .eq("id", courseId)
    .single()

  if (!course) {
    return new Response("Course not found", { status: 404 })
  }

  const lastUserMessage = [...messages]
    .reverse()
    .find((m) => m.role === "user")

  const lastUserText = lastUserMessage?.parts
    ?.filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text)
    .join(" ") ?? ""

  let contextChunks: string[] = []
  if (lastUserText) {
    try {
      const googleApiKey = provider === "google" ? apiKey : undefined
      const matches = await retrieveContext(lastUserText, courseId, undefined, googleApiKey)
      contextChunks = formatContextForPrompt(matches)
    } catch (e) {
      console.error("RAG retrieval failed, continuing without context:", e)
    }
  }

  const systemPrompt = buildSocraticSystemPrompt(course.name, contextChunks)

  const modelConfig: ModelConfig = { provider: provider as ModelConfig["provider"], model, apiKey }

  try {
    const result = streamText({
      model: resolveModel(modelConfig),
      system: systemPrompt,
      messages: await convertToModelMessages(messages),
      onFinish: async ({ text }) => {
        if (sessionId && text) {
          const serviceSupabase = await (
            await import("@/lib/supabase/server")
          ).createServiceClient()

          await serviceSupabase.from("messages").insert([
            {
              session_id: sessionId,
              role: "user" as const,
              content: lastUserText,
            },
            {
              session_id: sessionId,
              role: "assistant" as const,
              content: text,
            },
          ])

          await serviceSupabase
            .from("sessions")
            .update({ updated_at: new Date().toISOString() })
            .eq("id", sessionId)
        }
      },
    })

    return result.toUIMessageStreamResponse()
  } catch (error) {
    if (isQuotaError(error)) {
      return Response.json(
        { error: "API quota exceeded", code: "QUOTA_EXCEEDED" },
        { status: 429 }
      )
    }
    throw error
  }
}
