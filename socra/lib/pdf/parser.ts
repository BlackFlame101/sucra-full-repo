/* eslint-disable @typescript-eslint/no-require-imports */

export interface ParsedPDF {
  text: string
  pageCount: number
  pages: string[]
}

interface PdfTextItem {
  str?: string
  transform?: number[]
}

interface PdfPage {
  getTextContent(options: {
    normalizeWhitespace: boolean
    disableCombineTextItems: boolean
  }): Promise<{ items: PdfTextItem[] }>
}

interface PdfParseResult {
  text: string
  numpages: number
}

type PdfParse = (
  buffer: Buffer,
  options: { pagerender: (page: PdfPage) => Promise<string> },
) => Promise<PdfParseResult>

export function splitPdfPages(rawText: string, pageCount: number): string[] {
  if (!rawText.trim()) return Array.from({ length: pageCount }, () => "")
  if (!rawText.includes("\f")) {
    return [rawText.trim(), ...Array.from({ length: Math.max(0, pageCount - 1) }, () => "")]
  }

  // Keep blank pages so array positions continue to match the source PDF page numbers.
  const pages = rawText.split("\f").slice(0, pageCount).map((page) => page.trim())
  while (pages.length < pageCount) pages.push("")
  return pages
}

export async function parsePDF(buffer: Buffer): Promise<ParsedPDF> {
  // Import the inner module directly to bypass pdf-parse's index.js,
  // which runs a debug test on import that fails outside the package's own dir.
  const pdfParse = require("pdf-parse/lib/pdf-parse.js") as PdfParse
  const data = await pdfParse(buffer, {
    // pdf-parse otherwise joins every page with newlines. Add an explicit
    // page boundary so chunk metadata and citations retain real PDF pages.
    pagerender: async (pageData) => {
      const textContent = await pageData.getTextContent({
        normalizeWhitespace: false,
        disableCombineTextItems: false,
      })
      let lastY: number | undefined
      let pageText = ""
      for (const item of textContent.items) {
        if (typeof item.str !== "string" || !item.transform) continue
        const y = item.transform[5]
        pageText += lastY === y || lastY === undefined ? item.str : `\n${item.str}`
        lastY = y
      }
      return `${pageText}\f`
    },
  })

  const rawText = data.text || ""
  const pageCount = data.numpages || 0
  const pages = splitPdfPages(rawText, pageCount)

  return {
    text: rawText.trim(),
    pageCount: pageCount || pages.length,
    pages,
  }
}
