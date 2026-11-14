import { createCipheriv, randomBytes } from "node:crypto"
import { createClient } from "@/lib/supabase/server"

export const uuidPattern = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i

export async function ownedDocument(client: Awaited<ReturnType<typeof createClient>>, id: string, ownerId: string) {
  if (!uuidPattern.test(id)) return null
  const { data } = await client.from("documents").select("*, courses!inner(user_id)")
    .eq("id", id).eq("courses.user_id", ownerId).maybeSingle()
  return data
}

export function protectDocumentKey(key: unknown, documentId: string) {
  if (typeof key !== "string" || !key.trim()) return undefined
  if (key.length > 512) throw new Error("The Gemini API key is invalid.")
  const secret = Buffer.from(process.env.SOCRA_JOB_ENCRYPTION_KEY ?? "", "base64")
  if (secret.length !== 32) throw new Error("Custom keys for PDF processing are unavailable. Use the default key or contact the app administrator.")
  const nonce = randomBytes(12)
  const cipher = createCipheriv("aes-256-gcm", secret, nonce)
  cipher.setAAD(Buffer.from(documentId))
  const encrypted = Buffer.concat([cipher.update(key.trim(), "utf8"), cipher.final(), cipher.getAuthTag()])
  return `${nonce.toString("base64")}.${encrypted.toString("base64")}`
}
