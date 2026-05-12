import { createServiceClient } from "@/lib/supabase/server"
import { generateSingleEmbedding } from "@/lib/embeddings/generate"
import type { EmbeddingMatch } from "@/types"

const DEFAULT_MATCH_COUNT = 5
const SIMILARITY_THRESHOLD = 0.3

export async function retrieveContext(
  query: string,
  courseId: string,
  matchCount = DEFAULT_MATCH_COUNT,
  googleApiKey?: string
): Promise<EmbeddingMatch[]> {
  const queryEmbedding = await generateSingleEmbedding(query, googleApiKey)

  const supabase = await createServiceClient()

  const { data, error } = await supabase.rpc("match_embeddings", {
    query_embedding: JSON.stringify(queryEmbedding),
    match_count: matchCount,
    filter_course_id: courseId,
  })

  if (error) {
    console.error("RAG retrieval error:", error)
    return []
  }

  return (data as EmbeddingMatch[]).filter(
    (match) => match.similarity >= SIMILARITY_THRESHOLD
  )
}

export function formatContextForPrompt(matches: EmbeddingMatch[]): string[] {
  return matches.map((match) => {
    const source = match.filename
      ? `[Source: ${match.filename}, Page ${match.page_number ?? "?"}]`
      : `[Page ${match.page_number ?? "?"}]`
    return `${source}\n${match.content}`
  })
}
