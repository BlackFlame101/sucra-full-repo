/* eslint-disable @typescript-eslint/no-require-imports */

export interface ParsedPDF {
  text: string
  pageCount: number
  pages: string[]
}

export async function parsePDF(buffer: Buffer): Promise<ParsedPDF> {
  // Import the inner module directly to bypass pdf-parse's index.js,
  // which runs a debug test on import that fails outside the package's own dir.
  const pdfParse = require("pdf-parse/lib/pdf-parse.js") as (
    buffer: Buffer
  ) => Promise<{ text: string; numpages: number }>

  const data = await pdfParse(buffer)

  // pdf-parse returns full text; split by form-feed for pages
  const rawText = data.text || ""

  let pages: string[]
  if (rawText.includes("\f")) {
    pages = rawText.split("\f").map((p) => p.trim()).filter(Boolean)
  } else {
    pages = rawText.trim() ? [rawText.trim()] : []
  }

  return {
    text: rawText.trim(),
    pageCount: data.numpages || pages.length,
    pages,
  }
}
