import { readFileSync } from "node:fs"
import { getDocumentProxy, getResolvedPDFJS } from "unpdf"

async function markBoldHeadingFonts(page, runs, height) {
  const bodyFonts = new Set(runs.filter(([, y]) => y < height * .82 && y >= height * .035).map(run => run[3]))
  const candidates = runs.filter(([, y, size, font]) =>
    y >= height * .82 && size < 19 && !bodyFonts.has(font))
  if (!bodyFonts.size || !candidates.length) return

  // Text items expose opaque font IDs. The operator list loads their font metadata.
  await page.getOperatorList()
  for (const run of candidates) {
    const font = run[3]
    if (page.commonObjs.has(font) && page.commonObjs.get(font).bold) run.push(true)
  }
}

async function main() {
  const pdf = await getDocumentProxy(new Uint8Array(readFileSync(0)), { isEvalSupported: false })
  try {
    if (pdf.numPages > 300) {
      process.exitCode = 3
      return
    }
    let size = 0
    const pages = []
    const withLayout = process.argv.includes("--layout")
    const withEvidence = withLayout && process.argv.includes("--evidence")
    const ops = withEvidence ? (await getResolvedPDFJS()).OPS : null
    let remainingGeometry = 40000
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
      const page = await pdf.getPage(pageNumber)
      const stream = page.streamTextContent().getReader()
      try {
        let text = ""
        let previousY
        const runs = []
        const items = []
        let geometryTruncated = false
        while (true) {
          const { value, done } = await stream.read()
          if (done) break
          for (const item of value.items) {
            if (typeof item.str !== "string") continue
            const y = item.transform[5]
            if (previousY !== undefined && previousY !== y && !text.endsWith("\n")) text += "\n"
            if (withLayout && item.str.trim()) {
              runs.push([text.length, y, item.height, item.fontName])
              if (withEvidence) {
                if (items.length < 8000 && remainingGeometry > 0) {
                  items.push([text.length, item.str.length, item.transform[4], y, item.width, item.height])
                  remainingGeometry--
                } else {
                  geometryTruncated = true
                }
              }
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
        if (withLayout) {
          const height = page.getViewport({ scale: 1 }).height
          await markBoldHeadingFonts(page, runs, height)
          const output = { text, runs, height }
          if (withEvidence) {
            const viewport = page.getViewport({ scale: 1 })
            output.evidence = { items, width: viewport.width, geometry_truncated: geometryTruncated }
            try {
              const { fnArray, argsArray } = await page.getOperatorList()
              output.evidence.graphics = graphics(fnArray, argsArray, ops, viewport)
            } catch {
              output.evidence.graphics_unavailable = true
            }
          }
          pages.push(output)
        } else {
          pages.push(text.trim())
        }
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

function graphics(operators, argumentsList, ops, viewport) {
  let matrix = [1, 0, 0, 1, 0, 0]
  const stack = []
  const images = []
  let paths = 0
  let truncated = false
  for (let i = 0; i < operators.length; i++) {
    const operation = operators[i]
    const args = argumentsList[i]
    if (operation === ops.save || operation === ops.paintFormXObjectBegin) stack.push(matrix)
    if (operation === ops.restore || operation === ops.paintFormXObjectEnd) matrix = stack.pop() ?? matrix
    const transform = operation === ops.transform ? args : operation === ops.paintFormXObjectBegin ? args?.[0] : null
    if (transform) {
      const [a, b, c, d, x, y] = matrix
      const [e, f, g, h, u, v] = transform
      matrix = [a*e+c*f, b*e+d*f, a*g+c*h, b*g+d*h, a*u+c*v+x, b*u+d*v+y]
    }
    if (operation === ops.constructPath || operation === ops.shadingFill) paths++
    if ([ops.paintImageXObject, ops.paintInlineImageXObject, ops.paintImageMaskXObject].includes(operation)) {
      if (images.length >= 48) {
        truncated = true
        continue
      }
      const [a, b, c, d, x, y] = matrix
      const points = [[x, y], [x+a, y+b], [x+c, y+d], [x+a+c, y+b+d]]
        .map(([px, py]) => viewport.convertToViewportPoint(px, py))
      const xs = points.map(p => p[0])
      const ys = points.map(p => p[1])
      images.push([Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)])
    }
  }
  return { images, paths, truncated }
}

main().catch(() => { process.exitCode = 2 })
