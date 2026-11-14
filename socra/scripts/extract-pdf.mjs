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
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
      const page = await pdf.getPage(pageNumber)
      const stream = page.streamTextContent().getReader()
      try {
        let text = ""
        let previousY
        while (true) {
          const { value, done } = await stream.read()
          if (done) break
          for (const item of value.items) {
            if (typeof item.str !== "string") continue
            const y = item.transform[5]
            if (previousY !== undefined && previousY !== y && !text.endsWith("\n")) text += "\n"
            text += item.str + (item.hasEOL ? "\n" : "")
            if (size + text.length > 1_000_000) {
              process.exitCode = 3
              return
            }
            previousY = y
          }
        }
        size += text.length
        pages.push(text.trim())
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
