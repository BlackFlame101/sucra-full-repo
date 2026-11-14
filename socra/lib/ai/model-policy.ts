export const DEFAULT_GOOGLE_MODEL = "gemini-3.5-flash-lite"

const googleModelId = /^[a-z0-9][a-z0-9._-]*$/
const blockedGoogleModel = /^gemini-(?:2[.]5-flash(?:[-_].*)?|flash(?:-lite)?-latest)$/

export function resolveGoogleModel(model?: string) {
  const id = typeof model === "string" ? model.trim().toLowerCase().replace(/^models\//, "") : ""
  return !googleModelId.test(id) || blockedGoogleModel.test(id) ? DEFAULT_GOOGLE_MODEL : id
}
