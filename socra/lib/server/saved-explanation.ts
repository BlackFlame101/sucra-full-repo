import type { ExplanationPayload } from "@/lib/socra-ws"
import type { createClient } from "@/lib/supabase/server"
import { uuidPattern } from "@/lib/server/document-jobs"

export async function readSavedExplanation(client: Awaited<ReturnType<typeof createClient>>, owner: string,
  courseId: unknown, reference: unknown): Promise<ExplanationPayload | null> {
  if (typeof courseId !== "string" || !uuidPattern.test(courseId) || !reference || typeof reference !== "object" ||
      !("session_id" in reference) || typeof reference.session_id !== "string" || !uuidPattern.test(reference.session_id) ||
      !("message_id" in reference) || typeof reference.message_id !== "string" || !uuidPattern.test(reference.message_id)) return null
  const { data: session } = await client.from("sessions").select("id,courses!inner(user_id)")
    .eq("id", reference.session_id).eq("course_id", courseId).eq("courses.user_id", owner).maybeSingle()
  if (!session) return null
  const { data: message } = await client.from("messages").select("metadata")
    .eq("session_id", session.id).eq("id", reference.message_id).eq("role", "assistant").maybeSingle()
  const metadata = message?.metadata as { explanation?: ExplanationPayload } | null
  return metadata?.explanation ?? null
}
