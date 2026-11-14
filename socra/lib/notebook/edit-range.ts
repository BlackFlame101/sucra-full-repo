import type { Node } from "@tiptap/pm/model"

export type EditAnchor = { from: number; to: number; text: string; document: Node }
export type EditPlacement = "replace" | "below" | "end"

export function editRange(doc: Node, placement: EditPlacement, anchor: EditAnchor | null) {
  if (placement === "end") return doc.content.size
  if (!anchor || !anchor.document.eq(doc) || anchor.from < 0 || anchor.to > doc.content.size || anchor.from > anchor.to) return null
  if (placement === "replace") return anchor.from < anchor.to ? { from: anchor.from, to: anchor.to } : null
  const end = doc.resolve(anchor.to)
  return end.depth ? end.after(1) : end.pos
}
