import { GoogleGenerativeAI } from "@google/generative-ai"

const MODEL = "gemini-embedding-001"
const BATCH_SIZE = 100

function getClient(apiKey?: string): GoogleGenerativeAI {
  const key = apiKey || process.env.GEMINI_API_KEY
  if (!key) {
    throw new Error(
      "No Google API key available. Add GEMINI_API_KEY to .env.local or configure your own key in Settings."
    )
  }
  return new GoogleGenerativeAI(key)
}

export async function generateEmbeddings(
  texts: string[],
  googleApiKey?: string
): Promise<number[][]> {
  const client = getClient(googleApiKey)
  const model = client.getGenerativeModel({ model: MODEL })
  const embeddings: number[][] = []

  for (let i = 0; i < texts.length; i += BATCH_SIZE) {
    const batch = texts.slice(i, i + BATCH_SIZE)

    const result = await model.batchEmbedContents({
      requests: batch.map((text) => ({
        content: { role: "user", parts: [{ text }] },
        outputDimensionality: 768,
      })),
    })

    for (const item of result.embeddings) {
      embeddings.push(item.values)
    }
  }

  return embeddings
}

export async function generateSingleEmbedding(
  text: string,
  googleApiKey?: string
): Promise<number[]> {
  const [embedding] = await generateEmbeddings([text], googleApiKey)
  return embedding
}
