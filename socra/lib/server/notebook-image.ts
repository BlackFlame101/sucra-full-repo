import sharp from "sharp"
import { notebookImageFormats, notebookImageLimit } from "@/lib/notebook/images"

export async function prepareNotebookImage(request: Request) {
  const type = request.headers.get("content-type") ?? ""
  if (!Object.hasOwn(notebookImageFormats, type)) throw new Error("Use a PNG, JPEG, or WebP image.")
  const format = notebookImageFormats[type as keyof typeof notebookImageFormats]
  if (Number(request.headers.get("content-length")) > notebookImageLimit) throw new Error("Images must be 4 MiB or smaller.")
  const reader = request.body?.getReader()
  if (!reader) throw new Error("Choose an image to upload.")
  const chunks: Uint8Array[] = []
  let total = 0
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      total += value.byteLength
      if (total > notebookImageLimit) {
        await reader.cancel()
        throw new Error("Images must be 4 MiB or smaller.")
      }
      chunks.push(value)
    }
  } finally {
    reader.releaseLock()
  }
  const image = sharp(Buffer.concat(chunks), { limitInputPixels: 16_000_000, failOn: "warning" })
  let data: Buffer
  try {
    const { width, height, format: decoded, pages = 1 } = await image.metadata()
    if (decoded !== format || !width || !height || width > 8192 || height > 8192 || pages !== 1) {
      throw new Error("Invalid image.")
    }
    data = await image.autoOrient().toFormat(format).toBuffer()
  } catch {
    throw new Error("Use a valid, still PNG, JPEG, or WebP image within the image dimensions limit.")
  }
  if (data.length > notebookImageLimit) throw new Error("The processed image exceeds 4 MiB.")
  return { data, type, extension: format === "jpeg" ? "jpg" : format }
}

export async function prepareNotebookPdfImage(bytes: Buffer) {
  if (!bytes.length || bytes.length > notebookImageLimit) throw new Error("Invalid Notebook image size.")
  const image = sharp(bytes, { limitInputPixels: 16_000_000, failOn: "warning" })
  const { width, height, format, pages = 1 } = await image.metadata()
  if (!width || !height || width > 8192 || height > 8192 || width * height > 16_000_000 || pages !== 1 ||
      (format !== "png" && format !== "jpeg" && format !== "webp")) throw new Error("Invalid Notebook image.")
  return { width, height, data: format === "webp" ? await image.png().toBuffer() : bytes }
}
