export interface TextChunk {
  content: string
  pageNumber: number
  chunkIndex: number
}

const CHUNK_SIZE = 1000
const CHUNK_OVERLAP = 200

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4)
}

export function chunkPages(pages: string[]): TextChunk[] {
  const chunks: TextChunk[] = []
  let globalChunkIndex = 0

  for (let pageIdx = 0; pageIdx < pages.length; pageIdx++) {
    const pageText = pages[pageIdx].trim()
    if (!pageText) continue

    const pageNumber = pageIdx + 1

    // Split page into paragraphs to preserve natural boundaries
    const paragraphs = pageText.split(/\n{2,}/).filter((p) => p.trim())

    let currentChunk = ""

    for (const paragraph of paragraphs) {
      const cleaned = paragraph.replace(/\s+/g, " ").trim()
      if (!cleaned) continue

      const combinedTokens = estimateTokens(currentChunk + " " + cleaned)

      if (combinedTokens > CHUNK_SIZE && currentChunk) {
        chunks.push({
          content: currentChunk.trim(),
          pageNumber,
          chunkIndex: globalChunkIndex++,
        })

        // Keep overlap from the end of the previous chunk
        const words = currentChunk.trim().split(/\s+/)
        const overlapWordCount = Math.floor(
          words.length * (CHUNK_OVERLAP / CHUNK_SIZE)
        )
        const overlapText = words.slice(-overlapWordCount).join(" ")
        currentChunk = overlapText + " " + cleaned
      } else {
        currentChunk = currentChunk ? currentChunk + " " + cleaned : cleaned
      }
    }

    // Flush remaining text for this page
    if (currentChunk.trim()) {
      chunks.push({
        content: currentChunk.trim(),
        pageNumber,
        chunkIndex: globalChunkIndex++,
      })
    }
  }

  return chunks
}
