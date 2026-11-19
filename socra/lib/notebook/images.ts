export const notebookImageLimit = 4 * 1024 * 1024
export const notebookImageBucket = "notebook-images"
export const notebookImageFormats = { "image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp" } as const

const uuid = "[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
const imagePath = new RegExp(`^${uuid}/${uuid}\\.(?:png|jpg|webp)$`)

export function isNotebookImagePath(value: unknown): value is string {
  return typeof value === "string" && imagePath.test(value)
}

export function ownsNotebookImagePath(value: unknown, owner: string): value is string {
  return isNotebookImagePath(value) && value.startsWith(`${owner}/`)
}
