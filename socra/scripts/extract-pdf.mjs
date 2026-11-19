import { readFileSync } from "node:fs"
import { getDocumentProxy } from "unpdf"

async function main() {
  const pdf = await getDocumentProxy(new Uint8Array(readFileSync(0)), { isEvalSupported: false })
  try {
    if (pdf.numPages > 300) {
      process.exitCode = 3
      return
    }
    let size = 0
    const pages = []
    const layout = process.argv.includes("--code-layout")
    let geometryCount = 0
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
      const page = await pdf.getPage(pageNumber)
      const stream = page.streamTextContent().getReader()
      try {
        let text = ""
        let previousY
        const items = []
        while (true) {
          const { value, done } = await stream.read()
          if (done) break
          for (const item of value.items) {
            if (typeof item.str !== "string") continue
            const y = item.transform[5]
            if (previousY !== undefined && previousY !== y && !text.endsWith("\n")) text += "\n"
            if (layout && item.str.trim()) {
              if (++geometryCount > 40_000) {
                process.exitCode = 3
                return
              }
              items.push([text.length, item.str.length, item.transform[4], y, item.width, item.height])
            }
            text += item.str + (item.hasEOL ? "\n" : "")
            if (size + text.length > 1_000_000) {
              process.exitCode = 3
              return
            }
            previousY = y
          }
        }
        size += text.length
        pages.push(layout ? { text, items } : text.trim())
      } finally {
        await stream.cancel()
        page.cleanup()
      }
    }
    process.stdout.write(JSON.stringify(pages))
  } finally {
    await pdf.destroy()
  }
}

main().catch(() => { process.exitCode = 2 })
